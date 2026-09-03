import argparse
import asyncio
import csv
import json
import sys
from collections.abc import Mapping
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol, TextIO

import aiohttp
from google.transit import gtfs_realtime_pb2
from google.protobuf.message import DecodeError

from .realtime.source import SUPPORTED_PROTOBUF_MEDIA_TYPES


CompatibilityChecker = Callable[
    [str, Path, int], Awaitable["GtfsCompatibilityReport"]
]


class GtfsCompatibilityError(ValueError):
    """Raised when compatibility inputs cannot be validated."""


class _HttpResponse(Protocol):
    status: int
    headers: dict[str, str]

    async def __aenter__(self) -> "_HttpResponse": ...

    async def __aexit__(self, *_arguments: object) -> None: ...

    async def read(self) -> bytes: ...


class _HttpSession(Protocol):
    def get(self, url: str, *, headers: dict[str, str]) -> _HttpResponse: ...


@dataclass(frozen=True, slots=True)
class FetchedGtfsRealtimePayload:
    payload: bytes
    schedule_hash: str | None


@dataclass(frozen=True, slots=True)
class GtfsCompatibilityReport:
    """Compatibility counts between one GTFS-RT feed and static GTFS trips."""

    feed_timestamp: int | None
    schedule_hash: str | None
    total_trip_updates: int
    scheduled_trip_updates: int
    matched_scheduled_trip_ids: int
    unmatched_scheduled_trip_ids: int
    scheduled_match_ratio: float
    canceled_trip_updates: int
    matched_canceled_trip_ids: int
    unmatched_canceled_trip_ids: int
    exempt_non_scheduled_trip_ids: int
    matched_route_ids: int
    mismatched_route_ids: int
    missing_route_ids: int
    unmatched_scheduled_trip_id_sample: tuple[str, ...]
    route_id_mismatch_sample: tuple[dict[str, str], ...]


def analyze_gtfs_compatibility(
    feed: gtfs_realtime_pb2.FeedMessage,
    static_trip_routes: Mapping[str, str],
    *,
    schedule_hash: str | None = None,
    sample_limit: int = 5,
) -> GtfsCompatibilityReport:
    """Compare static-matchable GTFS-RT trip IDs with a static trip index."""
    if sample_limit < 0:
        raise ValueError("sample_limit must be non-negative")

    relationship = gtfs_realtime_pb2.TripDescriptor.ScheduleRelationship
    total_trip_updates = 0
    scheduled_trip_updates = 0
    matched_scheduled_trip_ids = 0
    unmatched_scheduled_trip_ids = 0
    canceled_trip_updates = 0
    matched_canceled_trip_ids = 0
    unmatched_canceled_trip_ids = 0
    exempt_non_scheduled_trip_ids = 0
    matched_route_ids = 0
    mismatched_route_ids = 0
    missing_route_ids = 0
    unmatched_sample_candidates: set[str] = set()
    route_mismatch_candidates: dict[str, dict[str, str]] = {}

    def compare_route_id(
        descriptor: gtfs_realtime_pb2.TripDescriptor,
        trip_id: str,
    ) -> None:
        nonlocal matched_route_ids, mismatched_route_ids, missing_route_ids
        realtime_route_id = (
            descriptor.route_id if descriptor.HasField("route_id") else ""
        )
        if not realtime_route_id:
            missing_route_ids += 1
        elif realtime_route_id == static_trip_routes[trip_id]:
            matched_route_ids += 1
        else:
            mismatched_route_ids += 1
            route_mismatch_candidates[trip_id] = {
                "trip_id": trip_id,
                "realtime_route_id": realtime_route_id,
                "static_route_id": static_trip_routes[trip_id],
            }

    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue

        total_trip_updates += 1
        descriptor = entity.trip_update.trip
        trip_id = descriptor.trip_id if descriptor.HasField("trip_id") else ""
        schedule_relationship = descriptor.schedule_relationship

        if schedule_relationship == relationship.SCHEDULED:
            scheduled_trip_updates += 1
            if trip_id and trip_id in static_trip_routes:
                matched_scheduled_trip_ids += 1
                compare_route_id(descriptor, trip_id)
            else:
                unmatched_scheduled_trip_ids += 1
                if trip_id:
                    unmatched_sample_candidates.add(trip_id)
        elif schedule_relationship == relationship.CANCELED:
            canceled_trip_updates += 1
            if trip_id and trip_id in static_trip_routes:
                matched_canceled_trip_ids += 1
                compare_route_id(descriptor, trip_id)
            else:
                unmatched_canceled_trip_ids += 1
        else:
            exempt_non_scheduled_trip_ids += 1

    scheduled_match_ratio = (
        matched_scheduled_trip_ids / scheduled_trip_updates
        if scheduled_trip_updates
        else 0.0
    )
    feed_timestamp = (
        int(feed.header.timestamp) if feed.header.HasField("timestamp") else None
    )

    return GtfsCompatibilityReport(
        feed_timestamp=feed_timestamp,
        schedule_hash=schedule_hash,
        total_trip_updates=total_trip_updates,
        scheduled_trip_updates=scheduled_trip_updates,
        matched_scheduled_trip_ids=matched_scheduled_trip_ids,
        unmatched_scheduled_trip_ids=unmatched_scheduled_trip_ids,
        scheduled_match_ratio=scheduled_match_ratio,
        canceled_trip_updates=canceled_trip_updates,
        matched_canceled_trip_ids=matched_canceled_trip_ids,
        unmatched_canceled_trip_ids=unmatched_canceled_trip_ids,
        exempt_non_scheduled_trip_ids=exempt_non_scheduled_trip_ids,
        matched_route_ids=matched_route_ids,
        mismatched_route_ids=mismatched_route_ids,
        missing_route_ids=missing_route_ids,
        unmatched_scheduled_trip_id_sample=tuple(
            sorted(unmatched_sample_candidates)[:sample_limit]
        ),
        route_id_mismatch_sample=tuple(
            route_mismatch_candidates[trip_id]
            for trip_id in sorted(route_mismatch_candidates)[:sample_limit]
        ),
    )


def load_static_trip_routes(trips_file: Path) -> dict[str, str]:
    """Load the GTFS trip-to-route relationship from trips.txt."""
    with trips_file.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not {"route_id", "trip_id"}.issubset(reader.fieldnames or ()):
            raise GtfsCompatibilityError(
                "trips.txt must contain columns: route_id, trip_id"
            )
        return {
            row["trip_id"].strip(): row["route_id"].strip()
            for row in reader
        }


def decode_gtfs_realtime_feed(payload: bytes) -> gtfs_realtime_pb2.FeedMessage:
    """Decode a GTFS-Realtime FeedMessage or raise a diagnostic error."""
    feed = gtfs_realtime_pb2.FeedMessage()
    try:
        feed.ParseFromString(payload)
    except DecodeError as error:
        raise GtfsCompatibilityError(
            "response is not valid GTFS-Realtime protobuf"
        ) from error
    if not feed.IsInitialized():
        raise GtfsCompatibilityError(
            "GTFS-Realtime protobuf is missing required fields"
        )
    return feed


def schedule_hash_from_content_type(content_type: str) -> str | None:
    """Extract VBB's optional schedule_sha256 media-type parameter."""
    for parameter in content_type.split(";")[1:]:
        name, separator, value = parameter.partition("=")
        if separator and name.strip().lower() == "schedule_sha256":
            return value.strip().strip('"') or None
    return None


async def fetch_gtfs_realtime_payload(
    session: _HttpSession,
    feed_url: str,
) -> FetchedGtfsRealtimePayload:
    """Fetch one GTFS-RT payload while preserving VBB schedule metadata."""
    async with session.get(
        feed_url,
        headers={"User-Agent": "bvg-3d-radar/1.0"},
    ) as response:
        if response.status != 200:
            raise GtfsCompatibilityError(
                f"GTFS-RT request failed with HTTP {response.status}"
            )
        content_type = response.headers.get("Content-Type", "")
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type not in SUPPORTED_PROTOBUF_MEDIA_TYPES:
            raise GtfsCompatibilityError(
                "Unexpected GTFS-RT Content-Type: "
                f"{media_type or '<missing>'}"
            )
        payload = await response.read()
        if not payload:
            raise GtfsCompatibilityError("GTFS-RT payload is empty")
    return FetchedGtfsRealtimePayload(
        payload=payload,
        schedule_hash=schedule_hash_from_content_type(content_type),
    )


async def check_live_compatibility(
    feed_url: str,
    trips_file: Path,
    sample_limit: int,
) -> GtfsCompatibilityReport:
    """Fetch and compare one live GTFS-RT snapshot with static trips.txt."""
    static_trip_routes = load_static_trip_routes(trips_file)
    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            fetched = await fetch_gtfs_realtime_payload(session, feed_url)
    except GtfsCompatibilityError:
        raise
    except (aiohttp.ClientError, TimeoutError) as error:
        raise GtfsCompatibilityError(
            f"GTFS-RT request failed: {error}"
        ) from error

    feed = decode_gtfs_realtime_feed(fetched.payload)
    return analyze_gtfs_compatibility(
        feed,
        static_trip_routes,
        schedule_hash=fetched.schedule_hash,
        sample_limit=sample_limit,
    )


def cli_main(
    argv: Sequence[str] | None = None,
    *,
    checker: CompatibilityChecker | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the compatibility gate and return a process-style exit code."""
    parser = argparse.ArgumentParser(
        description="Compare live VBB GTFS-RT trip IDs with static GTFS trips."
    )
    parser.add_argument("--feed-url", required=True)
    parser.add_argument("--trips-file", required=True, type=Path)
    parser.add_argument(
        "--minimum-scheduled-match",
        type=float,
        default=0.99,
    )
    parser.add_argument("--sample-limit", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args(argv)

    if arguments.sample_limit < 0:
        parser.error("--sample-limit must be non-negative")

    minimum_match = arguments.minimum_scheduled_match
    if not (0.0 <= minimum_match <= 1.0):
        parser.error("--minimum-scheduled-match must be between 0.0 and 1.0")

    output = sys.stdout if stdout is None else stdout
    error_output = sys.stderr if stderr is None else stderr
    effective_checker = check_live_compatibility if checker is None else checker
    try:
        report = asyncio.run(
            effective_checker(
                arguments.feed_url,
                arguments.trips_file,
                arguments.sample_limit,
            )
        )
    except (GtfsCompatibilityError, OSError) as error:
        if arguments.json:
            print(
                json.dumps({"error": str(error), "status": "error"}, sort_keys=True),
                file=error_output,
            )
        else:
            print(f"error: {error}", file=error_output)
        return 2
    compatible = (
        report.scheduled_match_ratio >= minimum_match
    )
    payload = {
        "minimum_scheduled_match": minimum_match,
        "report": asdict(report),
        "status": "compatible" if compatible else "incompatible",
    }
    if arguments.json:
        print(json.dumps(payload, sort_keys=True), file=output)
    else:
        print(
            f"{payload['status']}: "
            f"{report.matched_scheduled_trip_ids}/"
            f"{report.scheduled_trip_updates} scheduled trip IDs matched",
            file=output,
        )
    return 0 if compatible else 1
