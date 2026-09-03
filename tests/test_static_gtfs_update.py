import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

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
    assert manifest["archive_sha256"] == hashlib.sha256(
        archive_path.read_bytes()
    ).hexdigest()
    assert manifest["calendar_min_date"] == "2026-09-01"
    assert manifest["calendar_max_date"] == "2026-12-31"
    assert set(manifest["files"]) == set(EXPECTED_HEADERS)
    for filename in EXPECTED_HEADERS:
        assert manifest["files"][filename] == hashlib.sha256(
            (output_dir / filename).read_bytes()
        ).hexdigest()


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


def test_install_idempotent_when_output_exists(tmp_path: Path) -> None:
    archive_path = tmp_path / "valid.zip"
    _write_archive(archive_path, _valid_members())
    output_dir = tmp_path / "GTFS"
    manifest_path = tmp_path / "manifest.json"

    static_gtfs.install_static_gtfs_archive(
        archive_path=archive_path,
        output_dir=output_dir,
        manifest_path=manifest_path,
        source_url="https://unternehmen.vbb.de/gtfs",
        downloaded_at_utc="2026-09-03T09:00:00Z",
    )

    with pytest.raises(
        static_gtfs.StaticGtfsUpdateError,
        match="Output directory already exists",
    ):
        static_gtfs.install_static_gtfs_archive(
            archive_path=archive_path,
            output_dir=output_dir,
            manifest_path=manifest_path,
            source_url="https://unternehmen.vbb.de/gtfs",
            downloaded_at_utc="2026-09-03T09:00:00Z",
        )
