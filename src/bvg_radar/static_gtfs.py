"""Safe, auditable installation of a downloaded VBB static GTFS archive."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        with path.open(encoding="utf-8-sig", newline="") as source:
            actual_header = next(csv.reader(source), None)
        if actual_header != expected_header:
            raise StaticGtfsUpdateError(
                f"Unexpected header in {filename}: "
                f"expected {expected_header!r}, got {actual_header!r}"
            )


def _extract_safely(archive: ZipFile, target: Path) -> None:
    for member in archive.infolist():
        extracted_path = (target / member.filename).resolve()
        if not extracted_path.is_relative_to(target.resolve()):
            raise StaticGtfsUpdateError("Zip Slip: archive member escapes staging")
    archive.extractall(target)


def _calendar_range(directory: Path) -> tuple[str, str]:
    calendar_path = directory / "calendar.txt"
    dates: list[str] = []
    if calendar_path.is_file():
        with calendar_path.open(encoding="utf-8-sig", newline="") as source:
            for row in csv.DictReader(source):
                dates.extend((row["start_date"], row["end_date"]))
    if not dates:
        raise StaticGtfsUpdateError(
            "Static GTFS does not provide a calendar date range"
        )
    parsed = [datetime.strptime(value, "%Y%m%d").date() for value in dates]
    return min(parsed).isoformat(), max(parsed).isoformat()


def install_static_gtfs_archive(
    *,
    archive_path: Path,
    output_dir: Path,
    manifest_path: Path,
    source_url: str,
    downloaded_at_utc: str,
) -> dict[str, object]:
    """Validate an archive in staging, then install it and its manifest."""
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}.staging-",
            dir=output_dir.parent,
        )
    )
    try:
        with ZipFile(archive_path) as archive:
            _extract_safely(archive, staging_dir)
        _validate_required_headers(staging_dir)
        calendar_min_date, calendar_max_date = _calendar_range(staging_dir)
        manifest: dict[str, object] = {
            "source_url": source_url,
            "downloaded_at_utc": downloaded_at_utc,
            "archive_sha256": _sha256_file(archive_path),
            "files": {
                filename: _sha256_file(staging_dir / filename)
                for filename in EXPECTED_HEADERS
            },
            "calendar_min_date": calendar_min_date,
            "calendar_max_date": calendar_max_date,
        }
        if output_dir.exists():
            raise StaticGtfsUpdateError(
                f"Output directory already exists: {output_dir}"
            )
        staging_dir.replace(output_dir)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return manifest
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)