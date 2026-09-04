"""Command-line orchestration for a safe VBB static GTFS refresh."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

import aiohttp

from .gtfs_compatibility import GtfsCompatibilityError
from .static_gtfs import (
    DEFAULT_AGENCY_TIMEZONE,
    DEFAULT_MAX_FEED_AGE_SECONDS,
    DEFAULT_MAX_FUTURE_SKEW_SECONDS,
    DEFAULT_MINIMUM_UNIQUE_SCHEDULED_TRIP_IDS,
    StaticGtfsCompatibilityError,
    StaticGtfsUpdateError,
    StaticGtfsUpdateResult,
    update_static_gtfs,
    validate_static_gtfs_paths,
)

VBB_STATIC_GTFS_URL = "https://unternehmen.vbb.de/gtfs"
VBB_REALTIME_URL = "https://production.gtfsrt.vbb.de/data"
DEFAULT_OUTPUT_DIR = Path("data/gtfs-static/GTFS")
DEFAULT_MANIFEST_PATH = Path("data/gtfs-static/manifest.json")

StaticGtfsUpdater = Callable[..., Awaitable[StaticGtfsUpdateResult]]


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_operational_error(
    error: BaseException,
    *,
    json_output: bool,
    error_output: TextIO,
) -> None:
    if json_output:
        print(
            json.dumps({"error": str(error), "status": "error"}, sort_keys=True),
            file=error_output,
        )
    else:
        print(f"error: {error}", file=error_output)


async def _run_update(
    *,
    updater: StaticGtfsUpdater,
    static_url: str,
    realtime_url: str,
    archive_path: Path,
    output_dir: Path,
    manifest_path: Path,
    downloaded_at_utc: str,
    minimum_scheduled_match: float,
    minimum_unique_scheduled_trip_ids: int,
    max_feed_age_seconds: int,
    max_future_skew_seconds: int,
    sample_limit: int,
) -> StaticGtfsUpdateResult:
    timeout = aiohttp.ClientTimeout(total=300)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        return await updater(
            session=session,
            static_url=static_url,
            realtime_url=realtime_url,
            archive_path=archive_path,
            output_dir=output_dir,
            manifest_path=manifest_path,
            downloaded_at_utc=downloaded_at_utc,
            minimum_scheduled_match=minimum_scheduled_match,
            minimum_unique_scheduled_trip_ids=minimum_unique_scheduled_trip_ids,
            max_feed_age_seconds=max_feed_age_seconds,
            max_future_skew_seconds=max_future_skew_seconds,
            sample_limit=sample_limit,
        )


def cli_main(
    argv: Sequence[str] | None = None,
    *,
    updater: StaticGtfsUpdater = update_static_gtfs,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Download the VBB static GTFS archive, validate it in staging, "
            "and install it only when the live compatibility gate passes."
        )
    )
    parser.add_argument("--url", default=VBB_STATIC_GTFS_URL)
    parser.add_argument("--feed-url", default=VBB_REALTIME_URL)
    parser.add_argument(
        "--output",
        "--output-dir",
        dest="output_dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )
    parser.add_argument(
        "--manifest",
        dest="manifest_path",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
    )
    parser.add_argument(
        "--minimum-scheduled-match",
        type=float,
        default=0.99,
        help="Minimum unique SCHEDULED trip-ID match ratio (default: 0.99).",
    )
    parser.add_argument(
        "--minimum-unique-scheduled-trips",
        dest="minimum_unique_scheduled_trip_ids",
        type=int,
        default=DEFAULT_MINIMUM_UNIQUE_SCHEDULED_TRIP_IDS,
        help=(
            "Minimum unique SCHEDULED trip IDs required as representative "
            f"evidence (default: {DEFAULT_MINIMUM_UNIQUE_SCHEDULED_TRIP_IDS})."
        ),
    )
    parser.add_argument(
        "--max-feed-age-seconds",
        type=int,
        default=DEFAULT_MAX_FEED_AGE_SECONDS,
        help=(
            "Maximum GTFS-RT feed age in seconds "
            f"(default: {DEFAULT_MAX_FEED_AGE_SECONDS})."
        ),
    )
    parser.add_argument(
        "--max-future-skew-seconds",
        type=int,
        default=DEFAULT_MAX_FUTURE_SKEW_SECONDS,
        help=(
            "Maximum accepted future clock skew in seconds "
            f"(default: {DEFAULT_MAX_FUTURE_SKEW_SECONDS})."
        ),
    )
    parser.add_argument("--sample-limit", type=int, default=5)
    parser.add_argument("--keep-archive", action="store_true")
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args(argv)

    if arguments.sample_limit < 0:
        parser.error("--sample-limit must be non-negative")
    if not 0.0 <= arguments.minimum_scheduled_match <= 1.0:
        parser.error("--minimum-scheduled-match must be between 0.0 and 1.0")
    if arguments.minimum_unique_scheduled_trip_ids < 1:
        parser.error("--minimum-unique-scheduled-trips must be at least 1")
    if arguments.max_feed_age_seconds < 0:
        parser.error("--max-feed-age-seconds must be non-negative")
    if arguments.max_future_skew_seconds < 0:
        parser.error("--max-future-skew-seconds must be non-negative")

    compatibility_policy: dict[str, object] = {
        "agency_timezone": DEFAULT_AGENCY_TIMEZONE,
        "max_feed_age_seconds": arguments.max_feed_age_seconds,
        "max_future_skew_seconds": arguments.max_future_skew_seconds,
        "minimum_scheduled_match": arguments.minimum_scheduled_match,
        "minimum_unique_scheduled_trip_ids": (
            arguments.minimum_unique_scheduled_trip_ids
        ),
    }

    output = sys.stdout if stdout is None else stdout
    error_output = sys.stderr if stderr is None else stderr
    retained_archive_path = (
        arguments.output_dir.parent / "gtfs.zip"
        if arguments.keep_archive
        else None
    )
    archive_path: Path | None = None
    open_descriptor: int | None = None
    exit_code = 2
    payload: dict[str, object] | None = None
    plain_message = ""
    operational_error: BaseException | None = None

    try:
        validate_static_gtfs_paths(
            output_dir=arguments.output_dir,
            manifest_path=arguments.manifest_path,
            retained_archive_path=retained_archive_path,
        )
        arguments.output_dir.parent.mkdir(parents=True, exist_ok=True)
        arguments.manifest_path.parent.mkdir(parents=True, exist_ok=True)

        if retained_archive_path is not None:
            archive_path = retained_archive_path
        else:
            open_descriptor, archive_name = tempfile.mkstemp(
                prefix=".vbb-gtfs-",
                suffix=".zip",
                dir=arguments.output_dir.parent,
            )
            archive_path = Path(archive_name)
            os.close(open_descriptor)
            open_descriptor = None

        validate_static_gtfs_paths(
            output_dir=arguments.output_dir,
            manifest_path=arguments.manifest_path,
            archive_path=archive_path,
        )
        result = asyncio.run(
            _run_update(
                updater=updater,
                static_url=arguments.url,
                realtime_url=arguments.feed_url,
                archive_path=archive_path,
                output_dir=arguments.output_dir,
                manifest_path=arguments.manifest_path,
                downloaded_at_utc=_utc_timestamp(),
                minimum_scheduled_match=arguments.minimum_scheduled_match,
                minimum_unique_scheduled_trip_ids=(
                    arguments.minimum_unique_scheduled_trip_ids
                ),
                max_feed_age_seconds=arguments.max_feed_age_seconds,
                max_future_skew_seconds=arguments.max_future_skew_seconds,
                sample_limit=arguments.sample_limit,
            )
        )
        exit_code = 0
        payload = {
            "compatibility_policy": compatibility_policy,
            "compatibility_report": asdict(result.compatibility_report),
            "manifest": result.manifest,
            "minimum_scheduled_match": arguments.minimum_scheduled_match,
            "status": "installed",
        }
        plain_message = (
            "Installed compatible VBB static GTFS snapshot: "
            f"{result.compatibility_report.scheduled_match_ratio:.2%}"
        )
    except StaticGtfsCompatibilityError as error:
        exit_code = 1
        payload = {
            "compatibility_policy": compatibility_policy,
            "compatibility_report": asdict(error.report),
            "minimum_scheduled_match": error.minimum_scheduled_match,
            "status": "incompatible",
        }
        plain_message = str(error)
    except (
        StaticGtfsUpdateError,
        GtfsCompatibilityError,
        aiohttp.ClientError,
        TimeoutError,
        OSError,
        UnicodeError,
    ) as error:
        operational_error = error
    finally:
        cleanup_errors: list[OSError] = []
        if open_descriptor is not None:
            try:
                os.close(open_descriptor)
            except OSError as error:
                cleanup_errors.append(error)
        if archive_path is not None and retained_archive_path is None:
            try:
                archive_path.unlink(missing_ok=True)
            except OSError as error:
                cleanup_errors.append(error)
        if cleanup_errors:
            cleanup_detail = "; ".join(str(error) for error in cleanup_errors)
            prior_detail = (
                f"{operational_error}; " if operational_error is not None else ""
            )
            operational_error = StaticGtfsUpdateError(
                f"{prior_detail}could not clean temporary archive: {cleanup_detail}"
            )
            exit_code = 2

    if operational_error is not None:
        _write_operational_error(
            operational_error,
            json_output=arguments.json,
            error_output=error_output,
        )
        return 2
    if payload is None:
        raise RuntimeError("CLI completed without a result payload")
    if arguments.json:
        print(json.dumps(payload, sort_keys=True), file=output)
    else:
        print(plain_message, file=output)
    return exit_code
