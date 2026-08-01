"""Validate the VBB static GTFS headers expected by the Phase-1 local importer."""

import csv
import sys
from pathlib import Path

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


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: validate_vbb_gtfs_static.py <GTFS directory>")

    directory = Path(sys.argv[1]).resolve()
    failures: list[str] = []

    for filename, expected in EXPECTED_HEADERS.items():
        path = directory / filename
        if not path.is_file() or path.stat().st_size == 0:
            failures.append(f"Missing or empty: {path}")
            continue

        with path.open("r", encoding="utf-8-sig", newline="") as source:
            actual = next(csv.reader(source), None)

        if actual != expected:
            failures.append(
                f"Unexpected header in {filename}: expected {expected!r}, got {actual!r}"
            )
        else:
            print(f"Header validated: {filename} ({path.stat().st_size:,} bytes)")

    if failures:
        raise SystemExit("\n".join(failures))

    print("VBB static GTFS header validation: PASS")


if __name__ == "__main__":
    main()
