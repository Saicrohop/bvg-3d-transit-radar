"""Safe, auditable installation of a downloaded VBB static GTFS archive."""

from __future__ import annotations

import csv
import hashlib
import hmac
import json
import os
import shutil
import stat
import tempfile
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from zipfile import BadZipFile, ZipFile

from google.transit import gtfs_realtime_pb2

from .gtfs_compatibility import (
    GtfsCompatibilityReport,
    analyze_gtfs_compatibility,
    decode_gtfs_realtime_feed,
    fetch_gtfs_realtime_payload,
    load_static_trip_routes,
)


MAX_STATIC_ARCHIVE_BYTES = 512 * 1024 * 1024
DEFAULT_MINIMUM_UNIQUE_SCHEDULED_TRIP_IDS = 1000
DEFAULT_MAX_FEED_AGE_SECONDS = 900
DEFAULT_MAX_FUTURE_SKEW_SECONDS = 120
DEFAULT_AGENCY_TIMEZONE = "Europe/Berlin"


@dataclass(frozen=True, slots=True)
class StaticGtfsLimits:
    max_zip_members: int = 256
    max_member_uncompressed_bytes: int = 1024 * 1024 * 1024
    max_total_uncompressed_bytes: int = 2 * 1024 * 1024 * 1024
    max_compression_ratio: float = 200.0


EXPECTED_HEADERS = {
    "routes.txt": [
        "route_id",
        "agency_id",
        "route_short_name",
        "route_long_name",
        "route_type",
        "route_color",
        "route_text_color",
        "route_desc",
    ],
    "trips.txt": [
        "route_id",
        "service_id",
        "trip_id",
        "trip_headsign",
        "trip_short_name",
        "direction_id",
        "block_id",
        "shape_id",
        "wheelchair_accessible",
        "bikes_allowed",
    ],
    "stops.txt": [
        "stop_id",
        "stop_code",
        "stop_name",
        "stop_desc",
        "stop_lat",
        "stop_lon",
        "location_type",
        "parent_station",
        "wheelchair_boarding",
        "platform_code",
        "zone_id",
        "level_id",
    ],
    "shapes.txt": [
        "shape_id",
        "shape_pt_lat",
        "shape_pt_lon",
        "shape_pt_sequence",
    ],
    "stop_times.txt": [
        "trip_id",
        "stop_id",
        "stop_sequence",
        "pickup_type",
        "drop_off_type",
        "stop_headsign",
        "arrival_time",
        "departure_time",
    ],
}


class StaticGtfsUpdateError(ValueError):
    """Raised when a static GTFS archive cannot be installed safely."""


def _normalized_path(path: Path) -> Path:
    return Path(os.path.normcase(str(path.resolve())))


def validate_static_gtfs_paths(
    *,
    output_dir: Path,
    manifest_path: Path,
    archive_path: Path | None = None,
    retained_archive_path: Path | None = None,
) -> None:
    """Reject aliases that could overwrite snapshots, manifests, or archives."""
    output = _normalized_path(output_dir)
    named_paths: list[tuple[str, Path]] = [
        ("manifest", _normalized_path(manifest_path)),
    ]
    if archive_path is not None:
        named_paths.append(("archive", _normalized_path(archive_path)))
    if retained_archive_path is not None:
        named_paths.append(
            ("retained archive", _normalized_path(retained_archive_path))
        )

    for name, path in named_paths:
        if path == output or path.is_relative_to(output) or output.is_relative_to(path):
            raise StaticGtfsUpdateError(
                f"Static GTFS paths overlap: output and {name}"
            )
    for index, (left_name, left_path) in enumerate(named_paths):
        for right_name, right_path in named_paths[index + 1 :]:
            if left_path == right_path:
                raise StaticGtfsUpdateError(
                    f"Static GTFS paths overlap: {left_name} and {right_name}"
                )


@dataclass(frozen=True, slots=True)
class StaticGtfsUpdateResult:
    manifest: dict[str, object]
    compatibility_report: GtfsCompatibilityReport


class StaticGtfsCompatibilityError(StaticGtfsUpdateError):
    """Raised when a staged snapshot fails the live compatibility gate."""

    def __init__(
        self,
        report: GtfsCompatibilityReport,
        minimum_scheduled_match: float,
        *,
        reasons: list[str] | None = None,
    ) -> None:
        self.report = report
        self.minimum_scheduled_match = minimum_scheduled_match
        failure_reasons = [] if reasons is None else list(reasons)
        if report.scheduled_match_ratio < minimum_scheduled_match:
            failure_reasons.append(
                f"scheduled ratio {report.scheduled_match_ratio:.6f} "
                f"< {minimum_scheduled_match:.6f}"
            )
        if report.mismatched_route_ids:
            failure_reasons.append(
                f"{report.mismatched_route_ids} matched trip IDs have route mismatches"
            )
        super().__init__(
            "Staged GTFS snapshot is incompatible: " + "; ".join(failure_reasons)
        )


def validate_candidate_compatibility(
    candidate_dir: Path,
    feed: gtfs_realtime_pb2.FeedMessage,
    *,
    schedule_hash: str | None,
    minimum_scheduled_match: float,
    sample_limit: int,
    minimum_unique_scheduled_trip_ids: int = (
        DEFAULT_MINIMUM_UNIQUE_SCHEDULED_TRIP_IDS
    ),
    max_feed_age_seconds: int = DEFAULT_MAX_FEED_AGE_SECONDS,
    max_future_skew_seconds: int = DEFAULT_MAX_FUTURE_SKEW_SECONDS,
    agency_timezone: str = DEFAULT_AGENCY_TIMEZONE,
    now_utc: datetime | None = None,
) -> GtfsCompatibilityReport:
    """Fail closed unless staged trips match the current GTFS-RT feed."""
    if not 0.0 <= minimum_scheduled_match <= 1.0:
        raise StaticGtfsUpdateError(
            "minimum_scheduled_match must be between 0.0 and 1.0"
        )
    if sample_limit < 0:
        raise StaticGtfsUpdateError("sample_limit must be non-negative")
    if minimum_unique_scheduled_trip_ids < 1:
        raise StaticGtfsUpdateError(
            "minimum_unique_scheduled_trip_ids must be at least 1"
        )
    if max_feed_age_seconds < 0:
        raise StaticGtfsUpdateError("max_feed_age_seconds must be non-negative")
    if max_future_skew_seconds < 0:
        raise StaticGtfsUpdateError("max_future_skew_seconds must be non-negative")

    report = analyze_gtfs_compatibility(
        feed,
        load_static_trip_routes(candidate_dir / "trips.txt"),
        schedule_hash=schedule_hash,
        sample_limit=sample_limit,
    )
    failure_reasons: list[str] = []
    if report.unique_scheduled_trip_ids < minimum_unique_scheduled_trip_ids:
        failure_reasons.append(
            f"unique scheduled trip IDs {report.unique_scheduled_trip_ids} "
            f"< {minimum_unique_scheduled_trip_ids}"
        )
    if report.feed_timestamp is None:
        failure_reasons.append("feed timestamp is missing")
    else:
        effective_now = datetime.now(UTC) if now_utc is None else now_utc
        if effective_now.tzinfo is None:
            raise StaticGtfsUpdateError("now_utc must be timezone-aware")
        feed_time = datetime.fromtimestamp(report.feed_timestamp, UTC)
        feed_age_seconds = (
            effective_now.astimezone(UTC) - feed_time
        ).total_seconds()
        if feed_age_seconds > max_feed_age_seconds:
            failure_reasons.append(
                f"feed is stale by {feed_age_seconds:.0f} seconds "
                f"(maximum {max_feed_age_seconds})"
            )
        elif feed_age_seconds < -max_future_skew_seconds:
            failure_reasons.append(
                "feed timestamp is in the future by "
                f"{-feed_age_seconds:.0f} seconds "
                f"(maximum skew {max_future_skew_seconds})"
            )
        try:
            service_date = feed_time.astimezone(ZoneInfo(agency_timezone)).date()
        except ZoneInfoNotFoundError as error:
            raise StaticGtfsUpdateError(
                f"Unknown agency timezone: {agency_timezone}"
            ) from error
        calendar_min_date, calendar_max_date = _calendar_range(candidate_dir)
        service_date_text = service_date.isoformat()
        if not calendar_min_date <= service_date_text <= calendar_max_date:
            failure_reasons.append(
                f"feed service date {service_date_text} outside candidate calendar "
                f"{calendar_min_date}..{calendar_max_date}"
            )
    if (
        failure_reasons
        or report.scheduled_match_ratio < minimum_scheduled_match
        or report.mismatched_route_ids > 0
    ):
        raise StaticGtfsCompatibilityError(
            report,
            minimum_scheduled_match,
            reasons=failure_reasons,
        )
    return report


def _format_utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise StaticGtfsUpdateError("compatibility check time must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _build_compatibility_manifest_evidence(
    report: GtfsCompatibilityReport,
    *,
    checked_at_utc: datetime,
    minimum_scheduled_match: float,
    minimum_unique_scheduled_trip_ids: int,
    max_feed_age_seconds: int,
    max_future_skew_seconds: int,
    agency_timezone: str,
) -> dict[str, object]:
    if report.feed_timestamp is None:
        raise StaticGtfsUpdateError(
            "validated compatibility report has no feed timestamp"
        )
    checked_at_text = _format_utc_timestamp(checked_at_utc)
    feed_time = datetime.fromtimestamp(report.feed_timestamp, UTC)
    try:
        feed_service_date = feed_time.astimezone(
            ZoneInfo(agency_timezone)
        ).date().isoformat()
    except ZoneInfoNotFoundError as error:
        raise StaticGtfsUpdateError(
            f"Unknown agency timezone: {agency_timezone}"
        ) from error

    report_payload: dict[str, object] = asdict(report)
    report_payload["unmatched_scheduled_trip_id_sample"] = list(
        report.unmatched_scheduled_trip_id_sample
    )
    report_payload["route_id_mismatch_sample"] = [
        dict(item) for item in report.route_id_mismatch_sample
    ]
    return {
        "checked_at_utc": checked_at_text,
        "feed_age_seconds": int(
            (checked_at_utc.astimezone(UTC) - feed_time).total_seconds()
        ),
        "feed_service_date": feed_service_date,
        "policy": {
            "agency_timezone": agency_timezone,
            "max_feed_age_seconds": max_feed_age_seconds,
            "max_future_skew_seconds": max_future_skew_seconds,
            "minimum_scheduled_match": minimum_scheduled_match,
            "minimum_unique_scheduled_trip_ids": (
                minimum_unique_scheduled_trip_ids
            ),
        },
        "report": report_payload,
        "status": "compatible",
    }


class _DownloadContent(Protocol):
    def iter_chunked(self, chunk_size: int) -> AsyncIterator[bytes]: ...


class _DownloadResponse(Protocol):
    status: int
    content: _DownloadContent

    async def __aenter__(self) -> "_DownloadResponse": ...

    async def __aexit__(self, *_arguments: object) -> None: ...


class _DownloadSession(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
    ) -> _DownloadResponse: ...


async def download_archive(
    session: _DownloadSession,
    url: str,
    destination: Path,
    *,
    max_bytes: int = MAX_STATIC_ARCHIVE_BYTES,
) -> str:
    """Stream a bounded HTTP response to disk while calculating its SHA-256."""
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    async with session.get(
        url,
        headers={"User-Agent": "bvg-3d-radar/1.0"},
    ) as response:
        if response.status != 200:
            raise StaticGtfsUpdateError(
                f"Download failed with HTTP {response.status}"
            )

        temporary_file = tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{destination.name}.download-",
            dir=destination.parent,
            delete=False,
        )
        temporary_path = Path(temporary_file.name)
        bytes_written = 0
        try:
            with temporary_file:
                async for chunk in response.content.iter_chunked(1024 * 1024):
                    bytes_written += len(chunk)
                    if bytes_written > max_bytes:
                        raise StaticGtfsUpdateError(
                            f"Downloaded GTFS payload exceeds {max_bytes} bytes"
                        )
                    temporary_file.write(chunk)
                    digest.update(chunk)
            if bytes_written == 0:
                raise StaticGtfsUpdateError("Downloaded GTFS payload is empty")
            temporary_path.replace(destination)
        finally:
            temporary_path.unlink(missing_ok=True)
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_file_sha256s(snapshot_dir: Path) -> dict[str, str]:
    return {
        path.relative_to(snapshot_dir).as_posix(): _sha256_file(path)
        for path in sorted(snapshot_dir.rglob("*"))
        if path.is_file()
    }


def _validate_required_headers(directory: Path) -> None:
    missing = [
        filename
        for filename in EXPECTED_HEADERS
        if not (directory / filename).is_file()
    ]
    if missing:
        raise StaticGtfsUpdateError(
            f"Missing required GTFS files: {', '.join(sorted(missing))}"
        )

    for filename, expected_header in EXPECTED_HEADERS.items():
        path = directory / filename
        if path.stat().st_size == 0:
            raise StaticGtfsUpdateError(f"Empty required GTFS file: {filename}")
        try:
            with path.open(encoding="utf-8-sig", newline="") as source:
                actual_header = next(csv.reader(source, strict=True), None)
        except (UnicodeError, csv.Error) as error:
            raise StaticGtfsUpdateError(
                f"Cannot parse {filename}: {error}"
            ) from error
        if actual_header != expected_header:
            raise StaticGtfsUpdateError(
                f"Unexpected header in {filename}: "
                f"expected {expected_header!r}, got {actual_header!r}"
            )


def _extract_safely(
    archive: ZipFile,
    target: Path,
    limits: StaticGtfsLimits,
) -> None:
    members = archive.infolist()
    if len(members) > limits.max_zip_members:
        raise StaticGtfsUpdateError(
            f"ZIP archive contains {len(members)} members; "
            f"limit is {limits.max_zip_members}"
        )
    total_uncompressed_bytes = sum(
        member.file_size for member in members if not member.is_dir()
    )
    if total_uncompressed_bytes > limits.max_total_uncompressed_bytes:
        raise StaticGtfsUpdateError(
            "ZIP archive total uncompressed size "
            f"{total_uncompressed_bytes} exceeds "
            f"{limits.max_total_uncompressed_bytes} bytes"
        )
    target_resolved = target.resolve()
    extracted_paths: set[Path] = set()
    for member in members:
        if member.file_size > limits.max_member_uncompressed_bytes:
            raise StaticGtfsUpdateError(
                f"ZIP member {member.filename} uncompressed size "
                f"{member.file_size} exceeds "
                f"{limits.max_member_uncompressed_bytes} bytes"
            )
        compression_ratio = member.file_size / max(member.compress_size, 1)
        if compression_ratio > limits.max_compression_ratio:
            raise StaticGtfsUpdateError(
                f"ZIP member {member.filename} compression ratio "
                f"{compression_ratio:.1f} exceeds "
                f"{limits.max_compression_ratio:.1f}"
            )
        extracted_path = (target / member.filename).resolve()
        if not extracted_path.is_relative_to(target_resolved):
            raise StaticGtfsUpdateError("Zip Slip: archive member escapes staging")
        if extracted_path in extracted_paths:
            raise StaticGtfsUpdateError(
                f"Duplicate ZIP destination: {member.filename}"
            )
        extracted_paths.add(extracted_path)
        if stat.S_ISLNK(member.external_attr >> 16):
            raise StaticGtfsUpdateError(
                f"ZIP symbolic links are not allowed: {member.filename}"
            )
        if getattr(member, "flag_bits", 0) & 0x1:
            raise StaticGtfsUpdateError(
                f"Encrypted ZIP members are not allowed: {member.filename}"
            )

    target.mkdir(parents=True, exist_ok=True)
    expanded_total = 0
    for member in members:
        extracted_path = (target / member.filename).resolve()
        if member.is_dir():
            extracted_path.mkdir(parents=True, exist_ok=True)
            continue
        extracted_path.parent.mkdir(parents=True, exist_ok=True)
        expanded_member = 0
        try:
            with archive.open(member) as source, extracted_path.open("xb") as output:
                while chunk := source.read(1024 * 1024):
                    expanded_member += len(chunk)
                    expanded_total += len(chunk)
                    if expanded_member > limits.max_member_uncompressed_bytes:
                        raise StaticGtfsUpdateError(
                            f"ZIP member {member.filename} expanded beyond "
                            f"{limits.max_member_uncompressed_bytes} bytes"
                        )
                    if expanded_total > limits.max_total_uncompressed_bytes:
                        raise StaticGtfsUpdateError(
                            "ZIP archive expanded beyond "
                            f"{limits.max_total_uncompressed_bytes} bytes"
                        )
                    output.write(chunk)
            if expanded_member != member.file_size:
                raise StaticGtfsUpdateError(
                    f"ZIP member {member.filename} expanded size "
                    f"{expanded_member} differs from declared {member.file_size}"
                )
        except BaseException:
            extracted_path.unlink(missing_ok=True)
            raise


def _calendar_range(directory: Path) -> tuple[str, str]:
    calendar_path = directory / "calendar.txt"
    if not calendar_path.is_file() or calendar_path.stat().st_size == 0:
        raise StaticGtfsUpdateError(
            "Static GTFS does not provide a calendar date range"
        )

    dates: list[str] = []
    try:
        with calendar_path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source, strict=True)
            if not {"start_date", "end_date"}.issubset(reader.fieldnames or ()):
                raise StaticGtfsUpdateError(
                    "calendar.txt must contain start_date and end_date"
                )
            for row_number, row in enumerate(reader, start=2):
                for column in ("start_date", "end_date"):
                    value = row.get(column)
                    if not value or not value.strip():
                        raise StaticGtfsUpdateError(
                            f"Invalid calendar date at row {row_number}: "
                            f"missing {column}"
                        )
                    dates.append(value.strip())
    except StaticGtfsUpdateError:
        raise
    except (UnicodeError, csv.Error) as error:
        raise StaticGtfsUpdateError(
            f"Cannot parse calendar.txt: {error}"
        ) from error

    if not dates:
        raise StaticGtfsUpdateError(
            "Static GTFS does not provide a calendar date range"
        )
    try:
        parsed = [datetime.strptime(value, "%Y%m%d").date() for value in dates]
    except ValueError as error:
        raise StaticGtfsUpdateError(f"Invalid calendar date: {error}") from error
    return min(parsed).isoformat(), max(parsed).isoformat()


@contextmanager
def _exclusive_update_lock(lock_path: Path) -> Iterator[None]:
    """Hold a non-blocking process lock for one snapshot destination."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = lock_path.open("a+b")
    acquired = False
    try:
        if lock_path.stat().st_size == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        lock_file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise StaticGtfsUpdateError(
                "another static GTFS update is already in progress"
            ) from error
        acquired = True
        yield
    finally:
        if acquired:
            lock_file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


def _swap_artifact_paths(
    output_dir: Path,
    manifest_path: Path,
) -> tuple[Path, Path, Path, Path, Path]:
    backup_dir = output_dir.parent / f".{output_dir.name}.update-backup"
    manifest_backup = manifest_path.parent / f".{manifest_path.name}.update-backup"
    failed_dir = output_dir.parent / f".{output_dir.name}.update-failed"
    failed_manifest = manifest_path.parent / f".{manifest_path.name}.update-failed"
    journal_path = output_dir.parent / f".{output_dir.name}.update-journal.json"
    return backup_dir, manifest_backup, failed_dir, failed_manifest, journal_path


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _recover_interrupted_swap(
    *,
    output_dir: Path,
    manifest_path: Path,
    journal_path: Path,
) -> None:
    """Recover the previous snapshot/manifest pair from an update journal."""
    if not journal_path.exists():
        return
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StaticGtfsUpdateError(
            f"Cannot read static GTFS update journal: {error}"
        ) from error
    if not isinstance(journal, dict) or journal.get("version") != 1:
        raise StaticGtfsUpdateError("Unsupported static GTFS update journal")
    if journal.get("output_dir") != str(output_dir.resolve()) or journal.get(
        "manifest_path"
    ) != str(manifest_path.resolve()):
        raise StaticGtfsUpdateError(
            "Static GTFS update journal does not match requested paths"
        )

    backup_dir, manifest_backup, failed_dir, failed_manifest, _ = (
        _swap_artifact_paths(output_dir, manifest_path)
    )
    state = journal.get("state")
    if state == "committed":
        _remove_path(backup_dir)
        _remove_path(manifest_backup)
        _remove_path(failed_dir)
        _remove_path(failed_manifest)
        journal_path.unlink(missing_ok=True)
        return

    for failed_path in (failed_dir, failed_manifest):
        if failed_path.exists():
            raise StaticGtfsUpdateError(
                f"Cannot recover while stale artifact exists: {failed_path}"
            )

    had_output = journal.get("had_output") is True
    had_manifest = journal.get("had_manifest") is True
    promotion_started = state in {"promoting_snapshot", "promoting_manifest"}

    if backup_dir.exists():
        if output_dir.exists():
            output_dir.replace(failed_dir)
        backup_dir.replace(output_dir)
    elif had_output and not output_dir.exists():
        raise StaticGtfsUpdateError(
            "Cannot recover static GTFS snapshot: both active and backup are missing"
        )
    elif not had_output and promotion_started and output_dir.exists():
        output_dir.replace(failed_dir)

    if manifest_backup.exists():
        if manifest_path.exists():
            manifest_path.replace(failed_manifest)
        manifest_backup.replace(manifest_path)
    elif had_manifest and not manifest_path.exists():
        raise StaticGtfsUpdateError(
            "Cannot recover static GTFS manifest: both active and backup are missing"
        )
    elif not had_manifest and state == "promoting_manifest" and manifest_path.exists():
        manifest_path.replace(failed_manifest)

    _remove_path(failed_dir)
    _remove_path(failed_manifest)
    journal_path.unlink(missing_ok=True)


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    temporary_file = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        prefix=f".{path.name}.write-",
        dir=path.parent,
        delete=False,
    )
    temporary_path = Path(temporary_file.name)
    try:
        with temporary_file:
            json.dump(payload, temporary_file, indent=2, sort_keys=True)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _swap_staged_snapshot(
    *,
    staging_dir: Path,
    output_dir: Path,
    manifest_path: Path,
    manifest: dict[str, object],
) -> None:
    lock_path = output_dir.parent / f".{output_dir.name}.update.lock"
    backup_dir, manifest_backup, failed_dir, failed_manifest, journal_path = (
        _swap_artifact_paths(output_dir, manifest_path)
    )
    with _exclusive_update_lock(lock_path):
        _recover_interrupted_swap(
            output_dir=output_dir,
            manifest_path=manifest_path,
            journal_path=journal_path,
        )
        stale_artifacts = [
            path
            for path in (backup_dir, manifest_backup, failed_dir, failed_manifest)
            if path.exists()
        ]
        if stale_artifacts:
            raise StaticGtfsUpdateError(
                "Cannot start static GTFS swap with stale artifacts: "
                + ", ".join(str(path) for path in stale_artifacts)
            )

        manifest_file = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{manifest_path.name}.staging-",
            dir=manifest_path.parent,
            delete=False,
        )
        manifest_staging_path = Path(manifest_file.name)
        had_output = output_dir.exists()
        had_manifest = manifest_path.exists()
        journal: dict[str, object] = {
            "version": 1,
            "state": "prepared",
            "output_dir": str(output_dir.resolve()),
            "manifest_path": str(manifest_path.resolve()),
            "had_output": had_output,
            "had_manifest": had_manifest,
        }

        def set_state(state: str) -> None:
            journal["state"] = state
            _write_json_atomic(journal_path, journal)

        try:
            with manifest_file:
                json.dump(manifest, manifest_file, indent=2, sort_keys=True)
                manifest_file.write("\n")
                manifest_file.flush()
                os.fsync(manifest_file.fileno())

            set_state("prepared")
            if had_output:
                set_state("backing_up_snapshot")
                output_dir.replace(backup_dir)
            if had_manifest:
                set_state("backing_up_manifest")
                manifest_path.replace(manifest_backup)

            set_state("promoting_snapshot")
            staging_dir.replace(output_dir)
            set_state("promoting_manifest")
            manifest_staging_path.replace(manifest_path)
            set_state("committed")

            _remove_path(backup_dir)
            _remove_path(manifest_backup)
            journal_path.unlink(missing_ok=True)
        except (OSError, StaticGtfsUpdateError) as error:
            try:
                _recover_interrupted_swap(
                    output_dir=output_dir,
                    manifest_path=manifest_path,
                    journal_path=journal_path,
                )
            except (OSError, StaticGtfsUpdateError) as recovery_error:
                raise StaticGtfsUpdateError(
                    "Could not replace static GTFS snapshot and automatic recovery "
                    f"failed: {error}; recovery error: {recovery_error}; "
                    f"journal retained at {journal_path}"
                ) from recovery_error
            raise StaticGtfsUpdateError(
                f"Could not replace static GTFS snapshot; previous snapshot restored: "
                f"{error}"
            ) from error
        finally:
            manifest_staging_path.unlink(missing_ok=True)


def install_static_gtfs_archive(
    *,
    archive_path: Path,
    output_dir: Path,
    manifest_path: Path,
    source_url: str,
    downloaded_at_utc: str,
    archive_sha256: str | None = None,
    candidate_validator: Callable[[Path], dict[str, object] | None] | None = None,
    limits: StaticGtfsLimits | None = None,
) -> dict[str, object]:
    """Validate an archive in staging, then install it and its manifest."""
    validate_static_gtfs_paths(
        output_dir=output_dir,
        manifest_path=manifest_path,
        archive_path=archive_path,
    )
    verified_archive_sha256 = _sha256_file(archive_path)
    if archive_sha256 is not None and not hmac.compare_digest(
        archive_sha256,
        verified_archive_sha256,
    ):
        raise StaticGtfsUpdateError(
            "archive SHA-256 does not match downloaded file"
        )
    effective_limits = StaticGtfsLimits() if limits is None else limits
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}.staging-",
            dir=output_dir.parent,
        )
    )
    try:
        try:
            with ZipFile(archive_path) as archive:
                _extract_safely(archive, staging_dir, effective_limits)
        except BadZipFile as error:
            raise StaticGtfsUpdateError(
                "Downloaded payload is not a valid ZIP archive"
            ) from error
        _validate_required_headers(staging_dir)
        calendar_min_date, calendar_max_date = _calendar_range(staging_dir)
        compatibility_evidence = (
            candidate_validator(staging_dir)
            if candidate_validator is not None
            else None
        )
        manifest: dict[str, object] = {
            "source_url": source_url,
            "downloaded_at_utc": downloaded_at_utc,
            "installed_at_utc": _format_utc_timestamp(datetime.now(UTC)),
            "archive_sha256": verified_archive_sha256,
            "files": _snapshot_file_sha256s(staging_dir),
            "calendar_min_date": calendar_min_date,
            "calendar_max_date": calendar_max_date,
        }
        if compatibility_evidence is not None:
            manifest["compatibility"] = compatibility_evidence
        _swap_staged_snapshot(
            staging_dir=staging_dir,
            output_dir=output_dir,
            manifest_path=manifest_path,
            manifest=manifest,
        )
        return manifest
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)


async def update_static_gtfs(
    *,
    session: _DownloadSession,
    static_url: str,
    realtime_url: str,
    archive_path: Path,
    output_dir: Path,
    manifest_path: Path,
    downloaded_at_utc: str,
    minimum_scheduled_match: float,
    sample_limit: int,
    minimum_unique_scheduled_trip_ids: int = (
        DEFAULT_MINIMUM_UNIQUE_SCHEDULED_TRIP_IDS
    ),
    max_feed_age_seconds: int = DEFAULT_MAX_FEED_AGE_SECONDS,
    max_future_skew_seconds: int = DEFAULT_MAX_FUTURE_SKEW_SECONDS,
    agency_timezone: str = DEFAULT_AGENCY_TIMEZONE,
    now_utc: datetime | None = None,
) -> StaticGtfsUpdateResult:
    """Download and install only after the staged snapshot passes the live gate."""
    validate_static_gtfs_paths(
        output_dir=output_dir,
        manifest_path=manifest_path,
        archive_path=archive_path,
    )
    archive_sha256 = await download_archive(session, static_url, archive_path)
    fetched_realtime = await fetch_gtfs_realtime_payload(session, realtime_url)
    feed = decode_gtfs_realtime_feed(fetched_realtime.payload)
    compatibility_report: GtfsCompatibilityReport | None = None

    def validate_staged_candidate(candidate_dir: Path) -> dict[str, object]:
        nonlocal compatibility_report
        checked_at_utc = datetime.now(UTC) if now_utc is None else now_utc
        compatibility_report = validate_candidate_compatibility(
            candidate_dir,
            feed,
            schedule_hash=fetched_realtime.schedule_hash,
            minimum_scheduled_match=minimum_scheduled_match,
            minimum_unique_scheduled_trip_ids=minimum_unique_scheduled_trip_ids,
            max_feed_age_seconds=max_feed_age_seconds,
            max_future_skew_seconds=max_future_skew_seconds,
            agency_timezone=agency_timezone,
            now_utc=checked_at_utc,
            sample_limit=sample_limit,
        )
        return _build_compatibility_manifest_evidence(
            compatibility_report,
            checked_at_utc=checked_at_utc,
            minimum_scheduled_match=minimum_scheduled_match,
            minimum_unique_scheduled_trip_ids=minimum_unique_scheduled_trip_ids,
            max_feed_age_seconds=max_feed_age_seconds,
            max_future_skew_seconds=max_future_skew_seconds,
            agency_timezone=agency_timezone,
        )

    manifest = install_static_gtfs_archive(
        archive_path=archive_path,
        output_dir=output_dir,
        manifest_path=manifest_path,
        source_url=static_url,
        downloaded_at_utc=downloaded_at_utc,
        archive_sha256=archive_sha256,
        candidate_validator=validate_staged_candidate,
    )
    if compatibility_report is None:
        raise RuntimeError("candidate compatibility validator did not run")
    return StaticGtfsUpdateResult(
        manifest=manifest,
        compatibility_report=compatibility_report,
    )
