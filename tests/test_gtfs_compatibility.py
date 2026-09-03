import asyncio
import io
import json
from pathlib import Path

import aiohttp
from google.transit import gtfs_realtime_pb2
import pytest

from bvg_radar import gtfs_compatibility
from bvg_radar.gtfs_compatibility import (
    GtfsCompatibilityReport,
    analyze_gtfs_compatibility,
    cli_main,
)


def _add_trip_update(
    feed: gtfs_realtime_pb2.FeedMessage,
    *,
    entity_id: str,
    trip_id: str,
    route_id: str,
    relationship: int,
) -> None:
    entity = feed.entity.add()
    entity.id = entity_id
    descriptor = entity.trip_update.trip
    descriptor.trip_id = trip_id
    descriptor.route_id = route_id
    descriptor.start_date = "20260903"
    descriptor.schedule_relationship = relationship


def test_report_separates_scheduled_canceled_and_exempt_trip_ids() -> None:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = 1_788_380_145
    relationship = gtfs_realtime_pb2.TripDescriptor.ScheduleRelationship
    _add_trip_update(
        feed,
        entity_id="scheduled-matched",
        trip_id="trip-1",
        route_id="route-1",
        relationship=relationship.SCHEDULED,
    )
    _add_trip_update(
        feed,
        entity_id="scheduled-missing",
        trip_id="trip-2",
        route_id="route-2",
        relationship=relationship.SCHEDULED,
    )
    _add_trip_update(
        feed,
        entity_id="canceled-matched",
        trip_id="trip-canceled",
        route_id="route-canceled",
        relationship=relationship.CANCELED,
    )
    _add_trip_update(
        feed,
        entity_id="added-exempt",
        trip_id="trip-added",
        route_id="route-added",
        relationship=relationship.ADDED,
    )

    report = analyze_gtfs_compatibility(
        feed,
        {
            "trip-1": "route-1",
            "trip-canceled": "route-canceled",
        },
        schedule_hash="schedule-abc",
    )

    assert report.feed_timestamp == 1_788_380_145
    assert report.schedule_hash == "schedule-abc"
    assert report.total_trip_updates == 4
    assert report.scheduled_trip_updates == 2
    assert report.matched_scheduled_trip_ids == 1
    assert report.unmatched_scheduled_trip_ids == 1
    assert report.scheduled_match_ratio == 0.5
    assert report.canceled_trip_updates == 1
    assert report.matched_canceled_trip_ids == 1
    assert report.unmatched_canceled_trip_ids == 0
    assert report.exempt_non_scheduled_trip_ids == 1
    assert report.unmatched_scheduled_trip_id_sample == ("trip-2",)


def test_report_confirms_route_ids_for_static_matched_trips() -> None:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    relationship = gtfs_realtime_pb2.TripDescriptor.ScheduleRelationship
    _add_trip_update(
        feed,
        entity_id="route-mismatch",
        trip_id="trip-2",
        route_id="realtime-route",
        relationship=relationship.SCHEDULED,
    )
    missing_route = feed.entity.add()
    missing_route.id = "route-missing"
    missing_route.trip_update.trip.trip_id = "trip-1"
    missing_route.trip_update.trip.start_date = "20260903"

    report = analyze_gtfs_compatibility(
        feed,
        {
            "trip-1": "static-route-1",
            "trip-2": "static-route-2",
        },
    )

    assert report.matched_scheduled_trip_ids == 2
    assert report.matched_route_ids == 0
    assert report.mismatched_route_ids == 1
    assert report.missing_route_ids == 1
    assert report.route_id_mismatch_sample == (
        {
            "trip_id": "trip-2",
            "realtime_route_id": "realtime-route",
            "static_route_id": "static-route-2",
        },
    )


def test_report_fails_closed_when_feed_has_no_scheduled_trips() -> None:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    _add_trip_update(
        feed,
        entity_id="added-only",
        trip_id="trip-added",
        route_id="route-added",
        relationship=gtfs_realtime_pb2.TripDescriptor.ScheduleRelationship.ADDED,
    )

    report = analyze_gtfs_compatibility(feed, {})

    assert report.scheduled_trip_updates == 0
    assert report.scheduled_match_ratio == 0.0


def _compatibility_report(match_ratio: float) -> GtfsCompatibilityReport:
    return GtfsCompatibilityReport(
        feed_timestamp=1_788_380_145,
        schedule_hash="schedule-abc",
        total_trip_updates=4,
        scheduled_trip_updates=2,
        matched_scheduled_trip_ids=1,
        unmatched_scheduled_trip_ids=1,
        scheduled_match_ratio=match_ratio,
        canceled_trip_updates=1,
        matched_canceled_trip_ids=1,
        unmatched_canceled_trip_ids=0,
        exempt_non_scheduled_trip_ids=1,
        matched_route_ids=2,
        mismatched_route_ids=0,
        missing_route_ids=0,
        unmatched_scheduled_trip_id_sample=("trip-2",),
        route_id_mismatch_sample=(),
    )


def test_cli_returns_success_and_deterministic_json_above_threshold() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    async def checker(
        feed_url: str,
        trips_file: Path,
        sample_limit: int,
    ) -> GtfsCompatibilityReport:
        assert feed_url == "https://example.test/feed"
        assert trips_file == Path("static/trips.txt")
        assert sample_limit == 5
        return _compatibility_report(1.0)

    exit_code = cli_main(
        [
            "--feed-url",
            "https://example.test/feed",
            "--trips-file",
            "static/trips.txt",
            "--minimum-scheduled-match",
            "0.99",
            "--json",
        ],
        checker=checker,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    payload = json.loads(stdout.getvalue())
    assert payload["status"] == "compatible"
    assert payload["minimum_scheduled_match"] == 0.99
    assert payload["report"]["feed_timestamp"] == 1_788_380_145
    assert "generated_at" not in payload


def test_cli_returns_failure_below_threshold() -> None:
    stdout = io.StringIO()

    async def checker(
        feed_url: str,
        trips_file: Path,
        sample_limit: int,
    ) -> GtfsCompatibilityReport:
        return _compatibility_report(0.4)

    exit_code = cli_main(
        [
            "--feed-url",
            "https://example.test/feed",
            "--trips-file",
            "static/trips.txt",
            "--minimum-scheduled-match",
            "0.99",
            "--json",
        ],
        checker=checker,
        stdout=stdout,
    )

    assert exit_code == 1
    assert json.loads(stdout.getvalue())["status"] == "incompatible"


def test_cli_reports_operational_error_without_a_traceback() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    async def checker(
        feed_url: str,
        trips_file: Path,
        sample_limit: int,
    ) -> GtfsCompatibilityReport:
        raise OSError("static trips file is missing")

    exit_code = cli_main(
        [
            "--feed-url",
            "https://example.test/feed",
            "--trips-file",
            "missing/trips.txt",
            "--json",
        ],
        checker=checker,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "error": "static trips file is missing",
        "status": "error",
    }


def test_cli_reports_invalid_protobuf_as_operational_error() -> None:
    stderr = io.StringIO()

    async def checker(
        feed_url: str,
        trips_file: Path,
        sample_limit: int,
    ) -> GtfsCompatibilityReport:
        raise gtfs_compatibility.GtfsCompatibilityError(
            "response is not valid GTFS-Realtime protobuf"
        )

    exit_code = cli_main(
        [
            "--feed-url",
            "https://example.test/feed",
            "--trips-file",
            "static/trips.txt",
            "--json",
        ],
        checker=checker,
        stderr=stderr,
    )

    assert exit_code == 2
    assert json.loads(stderr.getvalue())["error"] == (
        "response is not valid GTFS-Realtime protobuf"
    )


def test_load_static_trip_routes_reads_trip_and_route_ids(tmp_path: Path) -> None:
    trips_file = tmp_path / "trips.txt"
    trips_file.write_text(
        "route_id,service_id,trip_id\n"
        "route-1,weekday,trip-1\n"
        "route-2,weekend,trip-2\n",
        encoding="utf-8",
    )

    routes = gtfs_compatibility.load_static_trip_routes(trips_file)

    assert routes == {"trip-1": "route-1", "trip-2": "route-2"}


def test_load_static_trip_routes_requires_trip_and_route_columns(
    tmp_path: Path,
) -> None:
    trips_file = tmp_path / "trips.txt"
    trips_file.write_text("trip_id\ntrip-1\n", encoding="utf-8")

    with pytest.raises(
        gtfs_compatibility.GtfsCompatibilityError,
        match="trips.txt must contain columns: route_id, trip_id",
    ):
        gtfs_compatibility.load_static_trip_routes(trips_file)


def test_decode_gtfs_realtime_feed_rejects_invalid_protobuf() -> None:
    with pytest.raises(
        gtfs_compatibility.GtfsCompatibilityError,
        match="response is not valid GTFS-Realtime protobuf",
    ):
        gtfs_compatibility.decode_gtfs_realtime_feed(b"not protobuf")


def test_decode_gtfs_realtime_feed_rejects_missing_required_header() -> None:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.entity.add().id = "entity-without-header"

    with pytest.raises(
        gtfs_compatibility.GtfsCompatibilityError,
        match="GTFS-Realtime protobuf is missing required fields",
    ):
        gtfs_compatibility.decode_gtfs_realtime_feed(
            feed.SerializePartialToString()
        )


def test_schedule_hash_from_content_type_extracts_vbb_parameter() -> None:
    schedule_hash = gtfs_compatibility.schedule_hash_from_content_type(
        "application/x-protobuf; schedule_sha256=abc123"
    )

    assert schedule_hash == "abc123"


class _FakeResponse:
    def __init__(
        self,
        payload: bytes,
        content_type: str,
        *,
        status: int = 200,
    ) -> None:
        self.status = status
        self.headers = {"Content-Type": content_type}
        self._payload = payload

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *_arguments: object) -> None:
        return None

    async def read(self) -> bytes:
        return self._payload


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, *, headers: dict[str, str]) -> _FakeResponse:
        self.calls.append((url, headers))
        return self.response

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *_arguments: object) -> None:
        return None


def test_fetch_gtfs_realtime_payload_preserves_schedule_hash() -> None:
    session = _FakeSession(
        _FakeResponse(
            b"protobuf bytes",
            "application/x-protobuf; schedule_sha256=abc123",
        )
    )

    fetched = asyncio.run(
        gtfs_compatibility.fetch_gtfs_realtime_payload(
            session,
            "https://example.test/feed",
        )
    )

    assert fetched.payload == b"protobuf bytes"
    assert fetched.schedule_hash == "abc123"
    assert session.calls == [
        (
            "https://example.test/feed",
            {"User-Agent": "bvg-3d-radar/1.0"},
        )
    ]


def test_fetch_gtfs_realtime_payload_rejects_non_protobuf_content_type() -> None:
    session = _FakeSession(_FakeResponse(b"<html />", "text/html"))

    with pytest.raises(
        gtfs_compatibility.GtfsCompatibilityError,
        match="Unexpected GTFS-RT Content-Type: text/html",
    ):
        asyncio.run(
            gtfs_compatibility.fetch_gtfs_realtime_payload(
                session,
                "https://example.test/feed",
            )
        )


def test_fetch_gtfs_realtime_payload_rejects_non_success_status() -> None:
    session = _FakeSession(
        _FakeResponse(
            b"upstream failure",
            "application/protobuf",
            status=503,
        )
    )

    with pytest.raises(
        gtfs_compatibility.GtfsCompatibilityError,
        match="GTFS-RT request failed with HTTP 503",
    ):
        asyncio.run(
            gtfs_compatibility.fetch_gtfs_realtime_payload(
                session,
                "https://example.test/feed",
            )
        )


def test_fetch_gtfs_realtime_payload_rejects_empty_body() -> None:
    session = _FakeSession(_FakeResponse(b"", "application/protobuf"))

    with pytest.raises(
        gtfs_compatibility.GtfsCompatibilityError,
        match="GTFS-RT payload is empty",
    ):
        asyncio.run(
            gtfs_compatibility.fetch_gtfs_realtime_payload(
                session,
                "https://example.test/feed",
            )
        )


def test_check_live_compatibility_connects_download_csv_decode_and_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trips_file = tmp_path / "trips.txt"
    trips_file.write_text(
        "route_id,service_id,trip_id\nroute-1,weekday,trip-1\n",
        encoding="utf-8",
    )
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = 1_788_380_145
    _add_trip_update(
        feed,
        entity_id="scheduled-matched",
        trip_id="trip-1",
        route_id="route-1",
        relationship=(
            gtfs_realtime_pb2.TripDescriptor.ScheduleRelationship.SCHEDULED
        ),
    )
    session = _FakeSession(
        _FakeResponse(
            feed.SerializeToString(),
            "application/x-protobuf; schedule_sha256=live-schedule",
        )
    )
    monkeypatch.setattr(
        aiohttp,
        "ClientSession",
        lambda **_arguments: session,
    )

    report = asyncio.run(
        gtfs_compatibility.check_live_compatibility(
            "https://example.test/feed",
            trips_file,
            3,
        )
    )

    assert report.scheduled_match_ratio == 1.0
    assert report.feed_timestamp == 1_788_380_145
    assert report.schedule_hash == "live-schedule"
    assert report.matched_route_ids == 1
