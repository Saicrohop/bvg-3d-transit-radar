import asyncio
import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from google.transit import gtfs_realtime_pb2

from bvg_radar import static_gtfs


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


def _csv_with_one_row(header: list[str]) -> str:
    return ",".join(header) + "\n" + ",".join(f"value-{i}" for i in range(len(header))) + "\n"


def _valid_members() -> dict[str, str]:
    members = {
        name: _csv_with_one_row(header)
        for name, header in EXPECTED_HEADERS.items()
    }
    members["calendar.txt"] = (
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
        "weekday,1,1,1,1,1,0,0,20260901,20261231\n"
    )
    members["agency.txt"] = "agency_id,agency_name\nag-1,VBB\n"
    return members


def _write_archive(path: Path, members: dict[str, str]) -> None:
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def _archive_bytes(members: dict[str, str]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


TEST_NOW_UTC = datetime(2026, 9, 3, 12, tzinfo=UTC)


def _feed_with_scheduled_trip(*, trip_id: str, route_id: str):
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = int(TEST_NOW_UTC.timestamp())
    entity = feed.entity.add()
    entity.id = "trip-update-1"
    entity.trip_update.trip.trip_id = trip_id
    entity.trip_update.trip.route_id = route_id
    entity.trip_update.trip.schedule_relationship = (
        gtfs_realtime_pb2.TripDescriptor.ScheduleRelationship.SCHEDULED
    )
    return feed


def _write_minimal_candidate(
    candidate_dir: Path,
    *,
    route_id: str,
    trip_id: str,
) -> None:
    candidate_dir.mkdir()
    (candidate_dir / "trips.txt").write_text(
        f"route_id,service_id,trip_id\n{route_id},weekday,{trip_id}\n",
        encoding="utf-8",
    )
    (candidate_dir / "calendar.txt").write_text(
        "service_id,start_date,end_date\n"
        "weekday,20260901,20261231\n",
        encoding="utf-8",
    )


def test_candidate_compatibility_accepts_matching_staged_trips(tmp_path: Path) -> None:
    candidate_dir = tmp_path / "candidate"
    _write_minimal_candidate(
        candidate_dir,
        route_id="route-1",
        trip_id="trip-1",
    )

    report = static_gtfs.validate_candidate_compatibility(
        candidate_dir,
        _feed_with_scheduled_trip(trip_id="trip-1", route_id="route-1"),
        schedule_hash="schedule-123",
        minimum_scheduled_match=0.99,
        minimum_unique_scheduled_trip_ids=1,
        now_utc=TEST_NOW_UTC,
        sample_limit=5,
    )

    assert report.scheduled_match_ratio == 1.0
    assert report.schedule_hash == "schedule-123"


def test_candidate_compatibility_rejects_missing_feed_timestamp(
    tmp_path: Path,
) -> None:
    candidate_dir = tmp_path / "candidate"
    _write_minimal_candidate(
        candidate_dir,
        route_id="route-1",
        trip_id="trip-1",
    )
    feed = _feed_with_scheduled_trip(trip_id="trip-1", route_id="route-1")
    feed.header.ClearField("timestamp")

    with pytest.raises(
        static_gtfs.StaticGtfsCompatibilityError,
        match="feed timestamp is missing",
    ):
        static_gtfs.validate_candidate_compatibility(
            candidate_dir,
            feed,
            schedule_hash="schedule-123",
            minimum_scheduled_match=0.99,
            minimum_unique_scheduled_trip_ids=1,
            max_feed_age_seconds=900,
            max_future_skew_seconds=120,
            now_utc=TEST_NOW_UTC,
            sample_limit=5,
        )


def test_candidate_compatibility_rejects_stale_feed_timestamp(
    tmp_path: Path,
) -> None:
    candidate_dir = tmp_path / "candidate"
    _write_minimal_candidate(
        candidate_dir,
        route_id="route-1",
        trip_id="trip-1",
    )
    feed = _feed_with_scheduled_trip(trip_id="trip-1", route_id="route-1")
    feed.header.timestamp = int(
        (TEST_NOW_UTC - timedelta(seconds=901)).timestamp()
    )

    with pytest.raises(
        static_gtfs.StaticGtfsCompatibilityError,
        match="feed is stale",
    ):
        static_gtfs.validate_candidate_compatibility(
            candidate_dir,
            feed,
            schedule_hash="schedule-123",
            minimum_scheduled_match=0.99,
            minimum_unique_scheduled_trip_ids=1,
            max_feed_age_seconds=900,
            max_future_skew_seconds=120,
            now_utc=TEST_NOW_UTC,
            sample_limit=5,
        )


def test_candidate_compatibility_rejects_future_feed_timestamp(
    tmp_path: Path,
) -> None:
    candidate_dir = tmp_path / "candidate"
    _write_minimal_candidate(
        candidate_dir,
        route_id="route-1",
        trip_id="trip-1",
    )
    feed = _feed_with_scheduled_trip(trip_id="trip-1", route_id="route-1")
    feed.header.timestamp = int(
        (TEST_NOW_UTC + timedelta(seconds=121)).timestamp()
    )

    with pytest.raises(
        static_gtfs.StaticGtfsCompatibilityError,
        match="feed timestamp is in the future",
    ):
        static_gtfs.validate_candidate_compatibility(
            candidate_dir,
            feed,
            schedule_hash="schedule-123",
            minimum_scheduled_match=0.99,
            minimum_unique_scheduled_trip_ids=1,
            max_feed_age_seconds=900,
            max_future_skew_seconds=120,
            now_utc=TEST_NOW_UTC,
            sample_limit=5,
        )


def test_candidate_compatibility_rejects_too_few_unique_scheduled_trips(
    tmp_path: Path,
) -> None:
    candidate_dir = tmp_path / "candidate"
    _write_minimal_candidate(
        candidate_dir,
        route_id="route-1",
        trip_id="trip-1",
    )
    feed = _feed_with_scheduled_trip(trip_id="trip-1", route_id="route-1")

    with pytest.raises(
        static_gtfs.StaticGtfsCompatibilityError,
        match="unique scheduled trip IDs 1 < 2",
    ):
        static_gtfs.validate_candidate_compatibility(
            candidate_dir,
            feed,
            schedule_hash="schedule-123",
            minimum_scheduled_match=0.99,
            minimum_unique_scheduled_trip_ids=2,
            max_feed_age_seconds=900,
            max_future_skew_seconds=120,
            now_utc=TEST_NOW_UTC,
            sample_limit=5,
        )


def test_candidate_compatibility_default_requires_representative_population(
    tmp_path: Path,
) -> None:
    candidate_dir = tmp_path / "candidate"
    _write_minimal_candidate(
        candidate_dir,
        route_id="route-1",
        trip_id="trip-1",
    )
    feed = _feed_with_scheduled_trip(trip_id="trip-1", route_id="route-1")

    with pytest.raises(
        static_gtfs.StaticGtfsCompatibilityError,
        match="unique scheduled trip IDs 1 < 1000",
    ):
        static_gtfs.validate_candidate_compatibility(
            candidate_dir,
            feed,
            schedule_hash="schedule-123",
            minimum_scheduled_match=0.99,
            max_feed_age_seconds=900,
            max_future_skew_seconds=120,
            now_utc=TEST_NOW_UTC,
            sample_limit=5,
        )


def test_candidate_compatibility_rejects_feed_date_outside_calendar(
    tmp_path: Path,
) -> None:
    candidate_dir = tmp_path / "candidate"
    _write_minimal_candidate(
        candidate_dir,
        route_id="route-1",
        trip_id="trip-1",
    )
    (candidate_dir / "calendar.txt").write_text(
        "service_id,start_date,end_date\n"
        "weekday,20260904,20261231\n",
        encoding="utf-8",
    )
    feed = _feed_with_scheduled_trip(trip_id="trip-1", route_id="route-1")

    with pytest.raises(
        static_gtfs.StaticGtfsCompatibilityError,
        match=(
            "feed service date 2026-09-03 outside candidate calendar "
            "2026-09-04..2026-12-31"
        ),
    ):
        static_gtfs.validate_candidate_compatibility(
            candidate_dir,
            feed,
            schedule_hash="schedule-123",
            minimum_scheduled_match=0.99,
            minimum_unique_scheduled_trip_ids=1,
            max_feed_age_seconds=900,
            max_future_skew_seconds=120,
            now_utc=TEST_NOW_UTC,
            sample_limit=5,
        )


def test_candidate_compatibility_rejects_mismatched_staged_trips(
    tmp_path: Path,
) -> None:
    candidate_dir = tmp_path / "candidate"
    _write_minimal_candidate(
        candidate_dir,
        route_id="route-2",
        trip_id="trip-2",
    )

    with pytest.raises(static_gtfs.StaticGtfsCompatibilityError) as captured:
        static_gtfs.validate_candidate_compatibility(
            candidate_dir,
            _feed_with_scheduled_trip(trip_id="trip-1", route_id="route-1"),
            schedule_hash="schedule-123",
            minimum_scheduled_match=0.99,
            minimum_unique_scheduled_trip_ids=1,
            now_utc=TEST_NOW_UTC,
            sample_limit=5,
        )

    assert captured.value.report.scheduled_match_ratio == 0.0
    assert captured.value.minimum_scheduled_match == 0.99


def test_candidate_compatibility_rejects_route_id_mismatch(tmp_path: Path) -> None:
    candidate_dir = tmp_path / "candidate"
    _write_minimal_candidate(
        candidate_dir,
        route_id="static-route",
        trip_id="trip-1",
    )

    with pytest.raises(static_gtfs.StaticGtfsCompatibilityError) as captured:
        static_gtfs.validate_candidate_compatibility(
            candidate_dir,
            _feed_with_scheduled_trip(
                trip_id="trip-1",
                route_id="realtime-route",
            ),
            schedule_hash="schedule-123",
            minimum_scheduled_match=0.99,
            minimum_unique_scheduled_trip_ids=1,
            now_utc=TEST_NOW_UTC,
            sample_limit=5,
        )

    assert captured.value.report.scheduled_match_ratio == 1.0
    assert captured.value.report.mismatched_route_ids == 1


def test_install_valid_archive_writes_snapshot_and_manifest(tmp_path: Path) -> None:
    archive_path = tmp_path / "vbb.zip"
    members = _valid_members()
    _write_archive(archive_path, members)
    output_dir = tmp_path / "GTFS"
    manifest_path = tmp_path / "manifest.json"

    manifest = static_gtfs.install_static_gtfs_archive(
        archive_path=archive_path,
        output_dir=output_dir,
        manifest_path=manifest_path,
        source_url="https://unternehmen.vbb.de/gtfs",
        downloaded_at_utc="2026-09-03T09:00:00Z",
    )

    assert {path.name for path in output_dir.iterdir()} == set(members)
    assert manifest == json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_url"] == "https://unternehmen.vbb.de/gtfs"
    assert manifest["downloaded_at_utc"] == "2026-09-03T09:00:00Z"
    installed_at = datetime.fromisoformat(
        str(manifest["installed_at_utc"]).replace("Z", "+00:00")
    )
    assert installed_at.tzinfo == UTC
    assert manifest["archive_sha256"] == hashlib.sha256(
        archive_path.read_bytes()
    ).hexdigest()
    assert manifest["calendar_min_date"] == "2026-09-01"
    assert manifest["calendar_max_date"] == "2026-12-31"
    assert set(manifest["files"]) == set(members)
    for filename in members:
        assert manifest["files"][filename] == hashlib.sha256(
            (output_dir / filename).read_bytes()
        ).hexdigest()


def test_install_rejects_unverified_archive_sha256(tmp_path: Path) -> None:
    archive_path = tmp_path / "vbb.zip"
    _write_archive(archive_path, _valid_members())
    output_dir = tmp_path / "GTFS"
    manifest_path = tmp_path / "manifest.json"

    with pytest.raises(
        static_gtfs.StaticGtfsUpdateError,
        match="archive SHA-256 does not match downloaded file",
    ):
        static_gtfs.install_static_gtfs_archive(
            archive_path=archive_path,
            output_dir=output_dir,
            manifest_path=manifest_path,
            source_url="https://example.test/gtfs.zip",
            downloaded_at_utc="2026-09-03T09:00:00Z",
            archive_sha256="0" * 64,
        )

    assert not output_dir.exists()
    assert not manifest_path.exists()


def test_install_rejects_archive_missing_required_file(tmp_path: Path) -> None:
    archive_path = tmp_path / "missing-stop-times.zip"
    members = _valid_members()
    del members["stop_times.txt"]
    _write_archive(archive_path, members)
    output_dir = tmp_path / "GTFS"
    manifest_path = tmp_path / "manifest.json"

    with pytest.raises(
        static_gtfs.StaticGtfsUpdateError,
        match=r"Missing required GTFS files: stop_times\.txt",
    ):
        static_gtfs.install_static_gtfs_archive(
            archive_path=archive_path,
            output_dir=output_dir,
            manifest_path=manifest_path,
            source_url="https://unternehmen.vbb.de/gtfs",
            downloaded_at_utc="2026-09-03T09:00:00Z",
        )

    assert not output_dir.exists()
    assert not manifest_path.exists()


def test_install_rejects_non_zip_payload(tmp_path: Path) -> None:
    archive_path = tmp_path / "not-a-zip.zip"
    archive_path.write_text("upstream error page", encoding="utf-8")

    with pytest.raises(
        static_gtfs.StaticGtfsUpdateError,
        match="valid ZIP archive",
    ):
        static_gtfs.install_static_gtfs_archive(
            archive_path=archive_path,
            output_dir=tmp_path / "GTFS",
            manifest_path=tmp_path / "manifest.json",
            source_url="https://unternehmen.vbb.de/gtfs",
            downloaded_at_utc="2026-09-03T09:00:00Z",
        )

    assert not (tmp_path / "GTFS").exists()
    assert not (tmp_path / "manifest.json").exists()


def test_install_rejects_invalid_utf8_in_required_file(tmp_path: Path) -> None:
    archive_path = tmp_path / "invalid-encoding.zip"
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        for filename, content in _valid_members().items():
            archive.writestr(
                filename,
                b"\xff" if filename == "trips.txt" else content,
            )

    with pytest.raises(
        static_gtfs.StaticGtfsUpdateError,
        match="Cannot parse trips.txt",
    ):
        static_gtfs.install_static_gtfs_archive(
            archive_path=archive_path,
            output_dir=tmp_path / "GTFS",
            manifest_path=tmp_path / "manifest.json",
            source_url="https://example.test/gtfs.zip",
            downloaded_at_utc="2026-09-03T09:00:00Z",
        )


def test_install_rejects_incompatible_required_header(tmp_path: Path) -> None:
    archive_path = tmp_path / "bad-header.zip"
    members = _valid_members()
    members["trips.txt"] = members["trips.txt"].replace(
        "trip_id",
        "journey_id",
        1,
    )
    _write_archive(archive_path, members)

    with pytest.raises(
        static_gtfs.StaticGtfsUpdateError,
        match="Unexpected header in trips.txt",
    ):
        static_gtfs.install_static_gtfs_archive(
            archive_path=archive_path,
            output_dir=tmp_path / "GTFS",
            manifest_path=tmp_path / "manifest.json",
            source_url="https://unternehmen.vbb.de/gtfs",
            downloaded_at_utc="2026-09-03T09:00:00Z",
        )


def test_install_rejects_invalid_calendar_date(tmp_path: Path) -> None:
    archive_path = tmp_path / "bad-calendar.zip"
    members = _valid_members()
    members["calendar.txt"] = members["calendar.txt"].replace(
        "20261231",
        "not-a-date",
    )
    _write_archive(archive_path, members)

    with pytest.raises(
        static_gtfs.StaticGtfsUpdateError,
        match="Invalid calendar date",
    ):
        static_gtfs.install_static_gtfs_archive(
            archive_path=archive_path,
            output_dir=tmp_path / "GTFS",
            manifest_path=tmp_path / "manifest.json",
            source_url="https://unternehmen.vbb.de/gtfs",
            downloaded_at_utc="2026-09-03T09:00:00Z",
        )


def test_install_rejects_short_calendar_row(tmp_path: Path) -> None:
    archive_path = tmp_path / "short-calendar-row.zip"
    members = _valid_members()
    members["calendar.txt"] = (
        "service_id,monday,start_date,end_date\n"
        "weekday,1,20260101\n"
    )
    _write_archive(archive_path, members)

    with pytest.raises(
        static_gtfs.StaticGtfsUpdateError,
        match="Invalid calendar date",
    ):
        static_gtfs.install_static_gtfs_archive(
            archive_path=archive_path,
            output_dir=tmp_path / "GTFS",
            manifest_path=tmp_path / "manifest.json",
            source_url="https://example.test/gtfs.zip",
            downloaded_at_utc="2026-09-03T09:00:00Z",
        )


def test_install_rejects_empty_required_file(tmp_path: Path) -> None:
    archive_path = tmp_path / "empty-stops.zip"
    members = _valid_members()
    members["stops.txt"] = ""
    _write_archive(archive_path, members)

    with pytest.raises(
        static_gtfs.StaticGtfsUpdateError,
        match="Empty required GTFS file: stops.txt",
    ):
        static_gtfs.install_static_gtfs_archive(
            archive_path=archive_path,
            output_dir=tmp_path / "GTFS",
            manifest_path=tmp_path / "manifest.json",
            source_url="https://unternehmen.vbb.de/gtfs",
            downloaded_at_utc="2026-09-03T09:00:00Z",
        )

    assert not (tmp_path / "GTFS").exists()
    assert not (tmp_path / "manifest.json").exists()


def test_install_rejects_zip_slip(tmp_path: Path) -> None:
    archive_path = tmp_path / "zip-slip.zip"
    members = _valid_members()
    members["../evil.txt"] = "exploit"
    _write_archive(archive_path, members)

    with pytest.raises(
        static_gtfs.StaticGtfsUpdateError,
        match="Zip Slip",
    ):
        static_gtfs.install_static_gtfs_archive(
            archive_path=archive_path,
            output_dir=tmp_path / "GTFS",
            manifest_path=tmp_path / "manifest.json",
            source_url="https://unternehmen.vbb.de/gtfs",
            downloaded_at_utc="2026-09-03T09:00:00Z",
        )

    assert not (tmp_path / "GTFS").exists()
    assert not (tmp_path / "manifest.json").exists()


def test_install_rejects_archive_with_too_many_members(tmp_path: Path) -> None:
    archive_path = tmp_path / "large-member-count.zip"
    _write_archive(archive_path, _valid_members())

    with pytest.raises(
        static_gtfs.StaticGtfsUpdateError,
        match="contains 7 members; limit is 1",
    ):
        static_gtfs.install_static_gtfs_archive(
            archive_path=archive_path,
            output_dir=tmp_path / "GTFS",
            manifest_path=tmp_path / "manifest.json",
            source_url="https://example.test/gtfs.zip",
            downloaded_at_utc="2026-09-03T09:00:00Z",
            limits=static_gtfs.StaticGtfsLimits(max_zip_members=1),
        )


def test_install_rejects_excessive_total_uncompressed_size(tmp_path: Path) -> None:
    archive_path = tmp_path / "large-expanded.zip"
    _write_archive(archive_path, _valid_members())

    with pytest.raises(
        static_gtfs.StaticGtfsUpdateError,
        match="total uncompressed size .* exceeds 1 bytes",
    ):
        static_gtfs.install_static_gtfs_archive(
            archive_path=archive_path,
            output_dir=tmp_path / "GTFS",
            manifest_path=tmp_path / "manifest.json",
            source_url="https://example.test/gtfs.zip",
            downloaded_at_utc="2026-09-03T09:00:00Z",
            limits=static_gtfs.StaticGtfsLimits(
                max_total_uncompressed_bytes=1
            ),
        )


def test_install_rejects_excessive_member_uncompressed_size(tmp_path: Path) -> None:
    archive_path = tmp_path / "large-member.zip"
    _write_archive(archive_path, _valid_members())

    with pytest.raises(
        static_gtfs.StaticGtfsUpdateError,
        match="routes.txt uncompressed size .* exceeds 1 bytes",
    ):
        static_gtfs.install_static_gtfs_archive(
            archive_path=archive_path,
            output_dir=tmp_path / "GTFS",
            manifest_path=tmp_path / "manifest.json",
            source_url="https://example.test/gtfs.zip",
            downloaded_at_utc="2026-09-03T09:00:00Z",
            limits=static_gtfs.StaticGtfsLimits(
                max_member_uncompressed_bytes=1
            ),
        )


def test_install_rejects_excessive_compression_ratio(tmp_path: Path) -> None:
    archive_path = tmp_path / "compression-bomb.zip"
    members = _valid_members()
    members["agency.txt"] = "agency_id,agency_name\n" + ("a,A\n" * 20_000)
    _write_archive(archive_path, members)

    with pytest.raises(
        static_gtfs.StaticGtfsUpdateError,
        match="compression ratio .* exceeds 2.0",
    ):
        static_gtfs.install_static_gtfs_archive(
            archive_path=archive_path,
            output_dir=tmp_path / "GTFS",
            manifest_path=tmp_path / "manifest.json",
            source_url="https://example.test/gtfs.zip",
            downloaded_at_utc="2026-09-03T09:00:00Z",
            limits=static_gtfs.StaticGtfsLimits(max_compression_ratio=2.0),
        )


class _ForgedZipMember:
    filename = "oversized.txt"
    file_size = 1
    compress_size = 1
    external_attr = 0

    def is_dir(self) -> bool:
        return False


class _ForgedZipArchive:
    def infolist(self) -> list[_ForgedZipMember]:
        return [_ForgedZipMember()]

    def open(self, _member: _ForgedZipMember):
        return BytesIO(b"123456")


def test_extraction_enforces_limits_on_actual_expanded_bytes(tmp_path: Path) -> None:
    with pytest.raises(
        static_gtfs.StaticGtfsUpdateError,
        match="expanded beyond 5 bytes",
    ):
        static_gtfs._extract_safely(
            _ForgedZipArchive(),
            tmp_path / "staging",
            static_gtfs.StaticGtfsLimits(
                max_member_uncompressed_bytes=5,
                max_total_uncompressed_bytes=10,
            ),
        )

    assert not (tmp_path / "staging" / "oversized.txt").exists()


def test_install_replaces_existing_snapshot_after_validation(tmp_path: Path) -> None:
    old_archive = tmp_path / "old.zip"
    old_members = _valid_members()
    old_members["agency.txt"] = "agency_id,agency_name\nag-1,Old VBB\n"
    _write_archive(old_archive, old_members)
    output_dir = tmp_path / "GTFS"
    manifest_path = tmp_path / "manifest.json"

    static_gtfs.install_static_gtfs_archive(
        archive_path=old_archive,
        output_dir=output_dir,
        manifest_path=manifest_path,
        source_url="https://example.test/old.zip",
        downloaded_at_utc="2026-09-02T09:00:00Z",
    )

    new_archive = tmp_path / "new.zip"
    new_members = _valid_members()
    new_members["agency.txt"] = "agency_id,agency_name\nag-1,New VBB\n"
    _write_archive(new_archive, new_members)

    manifest = static_gtfs.install_static_gtfs_archive(
        archive_path=new_archive,
        output_dir=output_dir,
        manifest_path=manifest_path,
        source_url="https://example.test/new.zip",
        downloaded_at_utc="2026-09-03T09:00:00Z",
    )

    assert (output_dir / "agency.txt").read_text(encoding="utf-8") == (
        "agency_id,agency_name\nag-1,New VBB\n"
    )
    assert manifest["source_url"] == "https://example.test/new.zip"
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == manifest
    assert not list(tmp_path.glob(".GTFS.backup-*"))


def test_candidate_validation_failure_preserves_existing_snapshot(
    tmp_path: Path,
) -> None:
    old_archive = tmp_path / "old.zip"
    old_members = _valid_members()
    old_members["agency.txt"] = "agency_id,agency_name\nag-1,Old VBB\n"
    _write_archive(old_archive, old_members)
    output_dir = tmp_path / "GTFS"
    manifest_path = tmp_path / "manifest.json"
    old_manifest = static_gtfs.install_static_gtfs_archive(
        archive_path=old_archive,
        output_dir=output_dir,
        manifest_path=manifest_path,
        source_url="https://example.test/old.zip",
        downloaded_at_utc="2026-09-02T09:00:00Z",
    )

    new_archive = tmp_path / "new.zip"
    new_members = _valid_members()
    new_members["agency.txt"] = "agency_id,agency_name\nag-1,New VBB\n"
    _write_archive(new_archive, new_members)

    def reject_candidate(staging_dir: Path) -> None:
        assert "New VBB" in (staging_dir / "agency.txt").read_text(
            encoding="utf-8"
        )
        raise static_gtfs.StaticGtfsUpdateError("candidate is incompatible")

    with pytest.raises(
        static_gtfs.StaticGtfsUpdateError,
        match="candidate is incompatible",
    ):
        static_gtfs.install_static_gtfs_archive(
            archive_path=new_archive,
            output_dir=output_dir,
            manifest_path=manifest_path,
            source_url="https://example.test/new.zip",
            downloaded_at_utc="2026-09-03T09:00:00Z",
            candidate_validator=reject_candidate,
        )

    assert "Old VBB" in (output_dir / "agency.txt").read_text(encoding="utf-8")
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == old_manifest
    assert not list(tmp_path.glob(".GTFS.staging-*"))


def test_recovery_restores_previous_pair_after_interrupted_promotion(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "GTFS"
    output_dir.mkdir()
    (output_dir / "marker.txt").write_text("new", encoding="utf-8")
    backup_dir = tmp_path / ".GTFS.update-backup"
    backup_dir.mkdir()
    (backup_dir / "marker.txt").write_text("old", encoding="utf-8")

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"version": "new"}', encoding="utf-8")
    manifest_backup = tmp_path / ".manifest.json.update-backup"
    manifest_backup.write_text('{"version": "old"}', encoding="utf-8")
    journal_path = tmp_path / ".GTFS.update-journal.json"
    journal_path.write_text(
        json.dumps(
            {
                "version": 1,
                "state": "promoting_manifest",
                "output_dir": str(output_dir.resolve()),
                "manifest_path": str(manifest_path.resolve()),
                "had_output": True,
                "had_manifest": True,
            }
        ),
        encoding="utf-8",
    )

    static_gtfs._recover_interrupted_swap(
        output_dir=output_dir,
        manifest_path=manifest_path,
        journal_path=journal_path,
    )

    assert (output_dir / "marker.txt").read_text(encoding="utf-8") == "old"
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == {
        "version": "old"
    }
    assert not backup_dir.exists()
    assert not manifest_backup.exists()
    assert not journal_path.exists()


def test_update_lock_rejects_concurrent_swap(tmp_path: Path) -> None:
    lock_path = tmp_path / ".GTFS.update.lock"

    with static_gtfs._exclusive_update_lock(lock_path):
        with pytest.raises(
            static_gtfs.StaticGtfsUpdateError,
            match="another static GTFS update is already in progress",
        ):
            with static_gtfs._exclusive_update_lock(lock_path):
                pass


def test_swap_failure_rolls_back_existing_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_archive = tmp_path / "old.zip"
    old_members = _valid_members()
    old_members["agency.txt"] = "agency_id,agency_name\nag-1,Old VBB\n"
    _write_archive(old_archive, old_members)
    output_dir = tmp_path / "GTFS"
    manifest_path = tmp_path / "manifest.json"
    old_manifest = static_gtfs.install_static_gtfs_archive(
        archive_path=old_archive,
        output_dir=output_dir,
        manifest_path=manifest_path,
        source_url="https://example.test/old.zip",
        downloaded_at_utc="2026-09-02T09:00:00Z",
    )

    new_archive = tmp_path / "new.zip"
    _write_archive(new_archive, _valid_members())
    original_replace = Path.replace

    def fail_staging_replace(self: Path, target: Path) -> Path:
        if self.name.startswith(".GTFS.staging-"):
            raise OSError("simulated staging swap failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_staging_replace)

    with pytest.raises(
        static_gtfs.StaticGtfsUpdateError,
        match="simulated staging swap failure",
    ):
        static_gtfs.install_static_gtfs_archive(
            archive_path=new_archive,
            output_dir=output_dir,
            manifest_path=manifest_path,
            source_url="https://example.test/new.zip",
            downloaded_at_utc="2026-09-03T09:00:00Z",
        )

    assert "Old VBB" in (output_dir / "agency.txt").read_text(encoding="utf-8")
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == old_manifest
    assert not list(tmp_path.glob(".GTFS.backup-*"))


def test_rollback_failure_retains_journal_for_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_archive = tmp_path / "old.zip"
    old_members = _valid_members()
    old_members["agency.txt"] = "agency_id,agency_name\nag-1,Old VBB\n"
    _write_archive(old_archive, old_members)
    output_dir = tmp_path / "GTFS"
    manifest_path = tmp_path / "manifest.json"
    static_gtfs.install_static_gtfs_archive(
        archive_path=old_archive,
        output_dir=output_dir,
        manifest_path=manifest_path,
        source_url="https://example.test/old.zip",
        downloaded_at_utc="2026-09-02T09:00:00Z",
    )

    new_archive = tmp_path / "new.zip"
    _write_archive(new_archive, _valid_members())
    original_replace = Path.replace

    def fail_promotion_and_recovery(self: Path, target: Path) -> Path:
        if self.name.startswith(".GTFS.staging-"):
            raise OSError("promotion failed")
        if self.name == ".GTFS.update-backup" and target == output_dir:
            raise OSError("snapshot locked")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_promotion_and_recovery)

    with pytest.raises(
        static_gtfs.StaticGtfsUpdateError,
        match="automatic recovery failed.*snapshot locked",
    ):
        static_gtfs.install_static_gtfs_archive(
            archive_path=new_archive,
            output_dir=output_dir,
            manifest_path=manifest_path,
            source_url="https://example.test/new.zip",
            downloaded_at_utc="2026-09-03T09:00:00Z",
        )

    assert (tmp_path / ".GTFS.update-journal.json").is_file()
    assert (tmp_path / ".GTFS.update-backup").is_dir()

    monkeypatch.setattr(Path, "replace", original_replace)
    static_gtfs._recover_interrupted_swap(
        output_dir=output_dir,
        manifest_path=manifest_path,
        journal_path=tmp_path / ".GTFS.update-journal.json",
    )

    assert "Old VBB" in (output_dir / "agency.txt").read_text(encoding="utf-8")
    assert manifest_path.is_file()
    assert not (tmp_path / ".GTFS.update-journal.json").exists()
    assert not (tmp_path / ".GTFS.update-backup").exists()


def test_manifest_swap_failure_rolls_back_existing_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_archive = tmp_path / "old.zip"
    old_members = _valid_members()
    old_members["agency.txt"] = "agency_id,agency_name\nag-1,Old VBB\n"
    _write_archive(old_archive, old_members)
    output_dir = tmp_path / "GTFS"
    manifest_path = tmp_path / "manifest.json"
    old_manifest = static_gtfs.install_static_gtfs_archive(
        archive_path=old_archive,
        output_dir=output_dir,
        manifest_path=manifest_path,
        source_url="https://example.test/old.zip",
        downloaded_at_utc="2026-09-02T09:00:00Z",
    )

    new_archive = tmp_path / "new.zip"
    new_members = _valid_members()
    new_members["agency.txt"] = "agency_id,agency_name\nag-1,New VBB\n"
    _write_archive(new_archive, new_members)
    original_replace = Path.replace

    def fail_manifest_replace(self: Path, target: Path) -> Path:
        if self.name.startswith(".manifest.json.staging-"):
            raise OSError("simulated manifest swap failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_manifest_replace)

    with pytest.raises(
        static_gtfs.StaticGtfsUpdateError,
        match="simulated manifest swap failure",
    ):
        static_gtfs.install_static_gtfs_archive(
            archive_path=new_archive,
            output_dir=output_dir,
            manifest_path=manifest_path,
            source_url="https://example.test/new.zip",
            downloaded_at_utc="2026-09-03T09:00:00Z",
        )

    assert "Old VBB" in (output_dir / "agency.txt").read_text(encoding="utf-8")
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == old_manifest
    assert not list(tmp_path.glob(".GTFS.backup-*"))
    assert not list(tmp_path.glob(".manifest.json.staging-*"))


class _FakeContent:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def iter_chunked(self, chunk_size: int):
        assert chunk_size == 1024 * 1024
        for chunk in self._chunks:
            yield chunk


class _FakeDownloadResponse:
    def __init__(self, *, status: int, chunks: list[bytes]) -> None:
        self.status = status
        self.content = _FakeContent(chunks)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_arguments: object) -> None:
        return None


class _FakeDownloadSession:
    def __init__(self, response: _FakeDownloadResponse) -> None:
        self._response = response
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, *, headers: dict[str, str]):
        assert url == "https://example.test/gtfs.zip"
        self.calls.append((url, headers))
        return self._response


def test_download_archive_streams_to_disk_and_hashes(tmp_path: Path) -> None:
    chunks = [b"first", b"-second"]
    destination = tmp_path / "gtfs.zip"
    session = _FakeDownloadSession(
        _FakeDownloadResponse(status=200, chunks=chunks)
    )

    digest = asyncio.run(
        static_gtfs.download_archive(
            session,
            "https://example.test/gtfs.zip",
            destination,
        )
    )

    expected_payload = b"".join(chunks)
    assert destination.read_bytes() == expected_payload
    assert digest == hashlib.sha256(expected_payload).hexdigest()
    assert session.calls == [
        (
            "https://example.test/gtfs.zip",
            {"User-Agent": "bvg-3d-radar/1.0"},
        )
    ]


def test_download_archive_rejects_empty_payload_and_removes_file(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "gtfs.zip"
    session = _FakeDownloadSession(
        _FakeDownloadResponse(status=200, chunks=[])
    )

    with pytest.raises(
        static_gtfs.StaticGtfsUpdateError,
        match="payload is empty",
    ):
        asyncio.run(
            static_gtfs.download_archive(
                session,
                "https://example.test/gtfs.zip",
                destination,
            )
        )

    assert not destination.exists()


def test_download_archive_rejects_payload_over_limit_and_removes_partial_file(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "gtfs.zip"
    session = _FakeDownloadSession(
        _FakeDownloadResponse(status=200, chunks=[b"1234", b"56"])
    )

    with pytest.raises(
        static_gtfs.StaticGtfsUpdateError,
        match="exceeds 5 bytes",
    ):
        asyncio.run(
            static_gtfs.download_archive(
                session,
                "https://example.test/gtfs.zip",
                destination,
                max_bytes=5,
            )
        )

    assert not destination.exists()
    assert not list(tmp_path.glob(".gtfs.zip.download-*"))


class _CombinedResponse:
    def __init__(
        self,
        body: bytes,
        *,
        content_type: str,
        status: int = 200,
    ) -> None:
        self.status = status
        self.headers = {"Content-Type": content_type}
        self.content = _FakeContent([body])
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_arguments: object) -> None:
        return None

    async def read(self) -> bytes:
        return self._body


class _CombinedSession:
    def __init__(self, responses: dict[str, _CombinedResponse]) -> None:
        self._responses = responses

    def get(self, url: str, *, headers: dict[str, str] | None = None):
        return self._responses[url]


def test_update_static_gtfs_gates_staged_trips_before_install(tmp_path: Path) -> None:
    members = _valid_members()
    members["trips.txt"] = (
        ",".join(EXPECTED_HEADERS["trips.txt"])
        + "\nroute-1,weekday,trip-1,headsign,short,0,block,shape,0,0\n"
    )
    feed = _feed_with_scheduled_trip(trip_id="trip-1", route_id="route-1")
    session = _CombinedSession(
        {
            "https://example.test/static.zip": _CombinedResponse(
                _archive_bytes(members),
                content_type="application/zip",
            ),
            "https://example.test/realtime": _CombinedResponse(
                feed.SerializeToString(),
                content_type=(
                    "application/x-protobuf; schedule_sha256=schedule-123"
                ),
            ),
        }
    )

    result = asyncio.run(
        static_gtfs.update_static_gtfs(
            session=session,
            static_url="https://example.test/static.zip",
            realtime_url="https://example.test/realtime",
            archive_path=tmp_path / "download.zip",
            output_dir=tmp_path / "GTFS",
            manifest_path=tmp_path / "manifest.json",
            downloaded_at_utc="2026-09-03T09:00:00Z",
            minimum_scheduled_match=0.99,
            minimum_unique_scheduled_trip_ids=1,
            now_utc=TEST_NOW_UTC,
            sample_limit=5,
        )
    )

    assert result.compatibility_report.scheduled_match_ratio == 1.0
    assert result.compatibility_report.schedule_hash == "schedule-123"
    expected_report = json.loads(json.dumps(asdict(result.compatibility_report)))
    assert result.manifest["compatibility"] == {
        "checked_at_utc": "2026-09-03T12:00:00Z",
        "feed_age_seconds": 0,
        "feed_service_date": "2026-09-03",
        "policy": {
            "agency_timezone": "Europe/Berlin",
            "max_feed_age_seconds": 900,
            "max_future_skew_seconds": 120,
            "minimum_scheduled_match": 0.99,
            "minimum_unique_scheduled_trip_ids": 1,
        },
        "report": expected_report,
        "status": "compatible",
    }
    assert set(result.manifest["compatibility"]["report"]) == set(
        asdict(result.compatibility_report)
    )
    assert result.manifest == json.loads(
        (tmp_path / "manifest.json").read_text(encoding="utf-8")
    )
    assert (tmp_path / "GTFS" / "trips.txt").is_file()


def test_update_static_gtfs_preserves_current_snapshot_when_gate_fails(
    tmp_path: Path,
) -> None:
    members = _valid_members()
    members["trips.txt"] = (
        ",".join(EXPECTED_HEADERS["trips.txt"])
        + "\nroute-2,weekday,trip-2,headsign,short,0,block,shape,0,0\n"
    )
    feed = _feed_with_scheduled_trip(trip_id="trip-1", route_id="route-1")
    session = _CombinedSession(
        {
            "https://example.test/static.zip": _CombinedResponse(
                _archive_bytes(members),
                content_type="application/zip",
            ),
            "https://example.test/realtime": _CombinedResponse(
                feed.SerializeToString(),
                content_type="application/x-protobuf",
            ),
        }
    )
    output_dir = tmp_path / "GTFS"
    output_dir.mkdir()
    (output_dir / "old-snapshot.txt").write_text("preserve me", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"snapshot":"old"}\n', encoding="utf-8")

    with pytest.raises(static_gtfs.StaticGtfsCompatibilityError):
        asyncio.run(
            static_gtfs.update_static_gtfs(
                session=session,
                static_url="https://example.test/static.zip",
                realtime_url="https://example.test/realtime",
                archive_path=tmp_path / "download.zip",
                output_dir=output_dir,
                manifest_path=manifest_path,
                downloaded_at_utc="2026-09-03T09:00:00Z",
                minimum_scheduled_match=0.99,
                sample_limit=5,
            )
        )

    assert (output_dir / "old-snapshot.txt").read_text(encoding="utf-8") == (
        "preserve me"
    )
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == {
        "snapshot": "old"
    }
    assert not list(tmp_path.glob(".GTFS.staging-*"))
