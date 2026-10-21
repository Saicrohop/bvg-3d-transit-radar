import csv
from datetime import date
from pathlib import Path

import pytest

from bvg_radar.planning.local_gtfs import (
    LocalGtfsDataError,
    OPERATION_UNCONFIRMED_MESSAGE,
    LocalGtfsSchedulePlanner,
    UnsupportedStopLocation,
)


SERVICE_DATE = date(2026, 10, 21)
TRANSFER_COLUMNS = [
    "from_stop_id",
    "to_stop_id",
    "transfer_type",
    "min_transfer_time",
    "from_route_id",
    "to_route_id",
    "from_trip_id",
    "to_trip_id",
]
PATHWAY_COLUMNS = [
    "pathway_id",
    "from_stop_id",
    "to_stop_id",
    "pathway_mode",
    "is_bidirectional",
    "traversal_time",
    "length",
    "stair_count",
    "max_slope",
    "min_width",
    "signposted_as",
]


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_transfers(directory: Path, rows: list[dict[str, str]]) -> None:
    _write_csv(directory / "transfers.txt", TRANSFER_COLUMNS, rows)


def _write_pathways(directory: Path, rows: list[dict[str, str]]) -> None:
    _write_csv(directory / "pathways.txt", PATHWAY_COLUMNS, rows)


def _transfer_row(
    from_stop_id: str,
    to_stop_id: str,
    transfer_type: int,
    min_transfer_time: int | None = None,
    from_route_id: str | None = None,
    to_route_id: str | None = None,
    from_trip_id: str | None = None,
    to_trip_id: str | None = None,
) -> dict[str, str]:
    return {
        "from_stop_id": from_stop_id,
        "to_stop_id": to_stop_id,
        "transfer_type": str(transfer_type),
        "min_transfer_time": "" if min_transfer_time is None else str(min_transfer_time),
        "from_route_id": from_route_id or "",
        "to_route_id": to_route_id or "",
        "from_trip_id": from_trip_id or "",
        "to_trip_id": to_trip_id or "",
    }


def _write_pathways(directory: Path, rows: list[dict[str, str]]) -> None:
    _write_csv(directory / "pathways.txt", PATHWAY_COLUMNS, rows)


def _pathway_row(
    pathway_id: str,
    from_stop_id: str,
    to_stop_id: str,
    traversal_time: int | None,
    *,
    is_bidirectional: int = 0,
    pathway_mode: int = 1,
) -> dict[str, str]:
    return {
        "pathway_id": pathway_id,
        "from_stop_id": from_stop_id,
        "to_stop_id": to_stop_id,
        "pathway_mode": str(pathway_mode),
        "is_bidirectional": str(is_bidirectional),
        "traversal_time": "" if traversal_time is None else str(traversal_time),
        "length": "",
        "stair_count": "",
        "max_slope": "",
        "min_width": "",
        "signposted_as": "",
    }


def _pathway_row(
    pathway_id: str,
    from_stop_id: str,
    to_stop_id: str,
    traversal_time: int | None,
    *,
    is_bidirectional: int = 0,
    pathway_mode: int = 1,
) -> dict[str, str]:
    return {
        "pathway_id": pathway_id,
        "from_stop_id": from_stop_id,
        "to_stop_id": to_stop_id,
        "pathway_mode": str(pathway_mode),
        "is_bidirectional": str(is_bidirectional),
        "traversal_time": "" if traversal_time is None else str(traversal_time),
        "length": "",
        "stair_count": "",
        "max_slope": "",
        "min_width": "",
        "signposted_as": "",
    }


def _write_gtfs(directory: Path) -> Path:
    directory.mkdir()
    _write_csv(
        directory / "routes.txt",
        ["route_id", "route_short_name"],
        [
            {"route_id": "R1", "route_short_name": "X1"},
            {"route_id": "R2", "route_short_name": "X2"},
            {"route_id": "R3", "route_short_name": "X3"},
            {"route_id": "R4", "route_short_name": "X4"},
            {"route_id": "R5", "route_short_name": "X5"},
            {"route_id": "R6", "route_short_name": "X6"},
        ],
    )
    _write_csv(
        directory / "trips.txt",
        ["route_id", "service_id", "trip_id", "trip_headsign", "direction_id"],
        [
            {"route_id": "R1", "service_id": "WEEKDAY", "trip_id": "before", "trip_headsign": "Early", "direction_id": "0"},
            {"route_id": "R2", "service_id": "WEEKDAY", "trip_id": "next", "trip_headsign": "Later", "direction_id": "1"},
            {"route_id": "R3", "service_id": "ONCE", "trip_id": "added", "trip_headsign": "Added", "direction_id": "0"},
            {"route_id": "R4", "service_id": "CANCELLED_SERVICE", "trip_id": "removed", "trip_headsign": "Removed", "direction_id": "0"},
            {"route_id": "R1", "service_id": "WEEKEND", "trip_id": "weekend", "trip_headsign": "Weekend", "direction_id": "0"},
            {"route_id": "R5", "service_id": "WEEKDAY", "trip_id": "overnight", "trip_headsign": "Night", "direction_id": "0"},
            {"route_id": "R6", "service_id": "WEEKDAY", "trip_id": "no-pickup", "trip_headsign": "Restricted", "direction_id": "0"},
            {"route_id": "R1", "service_id": "WEEKDAY", "trip_id": "transfer-leg", "trip_headsign": "Transfer", "direction_id": "0"},
            {"route_id": "R5", "service_id": "WEEKDAY", "trip_id": "transfer-leg-2", "trip_headsign": "Second Transfer", "direction_id": "0"},
            {"route_id": "R2", "service_id": "WEEKDAY", "trip_id": "pathway-leg", "trip_headsign": "Pathway", "direction_id": "0"},
            {"route_id": "R3", "service_id": "WEEKDAY", "trip_id": "pathway-incoming", "trip_headsign": "Reverse Pathway", "direction_id": "0"},
        ],
    )
    _write_csv(
        directory / "stops.txt",
        ["stop_id", "stop_name", "location_type", "parent_station"],
        [
            {"stop_id": "S1", "stop_name": "Start Platform", "location_type": "0", "parent_station": "STATION"},
            {"stop_id": "S2", "stop_name": "Destination Platform", "location_type": "0", "parent_station": "DEST_STATION"},
            {"stop_id": "S3", "stop_name": "Transfer Platform", "location_type": "0", "parent_station": "OTHER_STATION"},
            {"stop_id": "S4", "stop_name": "Final Platform", "location_type": "0", "parent_station": "FINAL_STATION"},
            {"stop_id": "S5", "stop_name": "Pathway Platform", "location_type": "0", "parent_station": "DEST_STATION"},
            {"stop_id": "PATH_NODE", "stop_name": "Station Walk Node", "location_type": "3", "parent_station": "DEST_STATION"},
            {"stop_id": "PATH_NODE_FAST", "stop_name": "Station Walk Node Fast", "location_type": "3", "parent_station": "DEST_STATION"},
            {"stop_id": "STATION", "stop_name": "Start Station", "location_type": "1", "parent_station": ""},
            {"stop_id": "DEST_STATION", "stop_name": "Destination Station", "location_type": "1", "parent_station": ""},
            {"stop_id": "OTHER_STATION", "stop_name": "Other Station", "location_type": "1", "parent_station": ""},
            {"stop_id": "FINAL_STATION", "stop_name": "Final Station", "location_type": "1", "parent_station": ""},
        ],
    )
    _write_csv(
        directory / "calendar.txt",
        ["service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "start_date", "end_date"],
        [
            {"service_id": "WEEKDAY", "monday": "0", "tuesday": "0", "wednesday": "1", "thursday": "0", "friday": "0", "saturday": "0", "sunday": "0", "start_date": "20261001", "end_date": "20261031"},
            {"service_id": "CANCELLED_SERVICE", "monday": "0", "tuesday": "0", "wednesday": "1", "thursday": "0", "friday": "0", "saturday": "0", "sunday": "0", "start_date": "20261001", "end_date": "20261031"},
            {"service_id": "WEEKEND", "monday": "0", "tuesday": "0", "wednesday": "0", "thursday": "0", "friday": "0", "saturday": "1", "sunday": "0", "start_date": "20261001", "end_date": "20261031"},
        ],
    )
    _write_csv(
        directory / "calendar_dates.txt",
        ["service_id", "date", "exception_type"],
        [
            {"service_id": "ONCE", "date": "20261021", "exception_type": "1"},
            {"service_id": "CANCELLED_SERVICE", "date": "20261021", "exception_type": "2"},
        ],
    )
    stop_time_rows = []
    schedules = {
        "before": ("08:20:00", "08:50:00"),
        "next": ("08:30:00", "09:00:00"),
        "added": ("08:25:00", "08:55:00"),
        "removed": ("08:27:00", "08:50:00"),
        "weekend": ("08:15:00", "08:40:00"),
        "overnight": ("25:10:00", "25:40:00"),
        "no-pickup": ("08:28:00", "08:55:00"),
    }
    for trip_id, (departure, arrival) in schedules.items():
        stop_time_rows.extend(
            [
                {"trip_id": trip_id, "stop_id": "S1", "stop_sequence": "1", "arrival_time": departure, "departure_time": departure, "pickup_type": "1" if trip_id == "no-pickup" else "0", "drop_off_type": "0"},
                {"trip_id": trip_id, "stop_id": "S2", "stop_sequence": "2", "arrival_time": arrival, "departure_time": arrival, "pickup_type": "0", "drop_off_type": "0"},
            ]
        )
    # A pair of trips via S2 must not be reported as a direct ride to S3.
    _write_csv(
        directory / "stop_times.txt",
        ["trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time", "pickup_type", "drop_off_type"],
        stop_time_rows
        + [
            {"trip_id": "transfer-leg", "stop_id": "S2", "stop_sequence": "1", "arrival_time": "09:00:00", "departure_time": "09:00:00", "pickup_type": "0", "drop_off_type": "0"},
            {"trip_id": "transfer-leg", "stop_id": "S3", "stop_sequence": "2", "arrival_time": "09:20:00", "departure_time": "09:20:00", "pickup_type": "0", "drop_off_type": "0"},
            {"trip_id": "transfer-leg-2", "stop_id": "S3", "stop_sequence": "1", "arrival_time": "09:30:00", "departure_time": "09:30:00", "pickup_type": "0", "drop_off_type": "0"},
            {"trip_id": "transfer-leg-2", "stop_id": "S4", "stop_sequence": "2", "arrival_time": "09:45:00", "departure_time": "09:45:00", "pickup_type": "0", "drop_off_type": "0"},
            {"trip_id": "pathway-leg", "stop_id": "S5", "stop_sequence": "1", "arrival_time": "08:51:40", "departure_time": "08:51:40", "pickup_type": "0", "drop_off_type": "0"},
            {"trip_id": "pathway-leg", "stop_id": "S4", "stop_sequence": "2", "arrival_time": "09:20:00", "departure_time": "09:20:00", "pickup_type": "0", "drop_off_type": "0"},
            {"trip_id": "pathway-incoming", "stop_id": "S4", "stop_sequence": "1", "arrival_time": "08:20:00", "departure_time": "08:20:00", "pickup_type": "0", "drop_off_type": "0"},
            {"trip_id": "pathway-incoming", "stop_id": "S5", "stop_sequence": "2", "arrival_time": "08:30:00", "departure_time": "08:30:00", "pickup_type": "0", "drop_off_type": "0"},
        ],
    )
    _write_transfers(directory, [])
    _write_pathways(directory, [])
    return directory


def test_finds_direct_schedule_journeys_and_labels_operation_unconfirmed(tmp_path: Path) -> None:
    planner = LocalGtfsSchedulePlanner(_write_gtfs(tmp_path / "GTFS"))

    journeys = planner.find_direct_journeys(
        origin_stop_id="S1",
        destination_stop_id="S2",
        service_date=SERVICE_DATE,
        departure_after="08:24:00",
    )

    assert [journey.trip_id for journey in journeys] == ["added", "next", "overnight"]
    assert [journey.departure_time for journey in journeys] == [
        "08:25:00",
        "08:30:00",
        "25:10:00",
    ]
    assert journeys[0].route_short_name == "X3"
    assert journeys[0].arrival_time == "08:55:00"
    assert journeys[0].duration_seconds == 30 * 60
    assert all(journey.operation_confirmed is False for journey in journeys)
    assert all(journey.operation_message == OPERATION_UNCONFIRMED_MESSAGE for journey in journeys)


def test_direct_prototype_does_not_synthesize_a_transfer_route(tmp_path: Path) -> None:
    planner = LocalGtfsSchedulePlanner(_write_gtfs(tmp_path / "GTFS"))

    journeys = planner.find_direct_journeys(
        origin_stop_id="S1",
        destination_stop_id="S3",
        service_date=SERVICE_DATE,
        departure_after="08:00:00",
    )

    assert journeys == ()


def test_finds_earliest_itinerary_through_an_explicit_minimum_transfer(
    tmp_path: Path,
) -> None:
    gtfs_directory = _write_gtfs(tmp_path / "GTFS")
    _write_transfers(
        gtfs_directory,
        [
            {
                "from_stop_id": "S2",
                "to_stop_id": "S2",
                "transfer_type": "2",
                "min_transfer_time": "300",
                "from_route_id": "",
                "to_route_id": "",
                "from_trip_id": "",
                "to_trip_id": "",
            }
        ],
    )
    planner = LocalGtfsSchedulePlanner(gtfs_directory)

    journey = planner.find_earliest_journey(
        origin_stop_id="S1",
        destination_stop_id="S3",
        service_date=SERVICE_DATE,
        departure_after="08:00:00",
    )

    assert journey is not None
    assert len(journey.legs) == 2
    assert journey.legs[0].from_stop_id == "S1"
    assert journey.legs[0].to_stop_id == "S2"
    assert journey.legs[1].from_stop_id == "S2"
    assert journey.legs[1].to_stop_id == "S3"
    assert len(journey.transfers) == 1
    assert journey.transfers[0].transfer_type == 2
    assert journey.transfers[0].min_transfer_time_seconds == 300
    assert journey.transfers[0].scheduled_gap_seconds >= 300
    assert journey.arrival_time == "09:20:00"
    assert journey.operation_confirmed is False
    assert journey.operation_message == OPERATION_UNCONFIRMED_MESSAGE


def test_does_not_infer_transfer_when_minimum_time_is_not_met(tmp_path: Path) -> None:
    gtfs_directory = _write_gtfs(tmp_path / "GTFS")
    _write_transfers(
        gtfs_directory,
        [
            {
                "from_stop_id": "S2",
                "to_stop_id": "S2",
                "transfer_type": "2",
                "min_transfer_time": "601",
                "from_route_id": "",
                "to_route_id": "",
                "from_trip_id": "",
                "to_trip_id": "",
            }
        ],
    )
    planner = LocalGtfsSchedulePlanner(gtfs_directory)

    journey = planner.find_earliest_journey(
        origin_stop_id="S1",
        destination_stop_id="S3",
        service_date=SERVICE_DATE,
        departure_after="08:00:00",
    )

    assert journey is None


def test_earliest_journey_can_be_a_direct_trip_without_transfers(tmp_path: Path) -> None:
    planner = LocalGtfsSchedulePlanner(_write_gtfs(tmp_path / "GTFS"))

    journey = planner.find_earliest_journey(
        origin_stop_id="S1",
        destination_stop_id="S2",
        service_date=SERVICE_DATE,
        departure_after="08:24:00",
    )

    assert journey is not None
    assert len(journey.legs) == 1
    assert journey.transfers == ()
    assert journey.legs[0].trip_id == "added"
    assert journey.departure_time == "08:25:00"


def test_timed_transfer_rule_is_preserved_without_inventing_a_minimum(
    tmp_path: Path,
) -> None:
    gtfs_directory = _write_gtfs(tmp_path / "GTFS")
    _write_transfers(gtfs_directory, [_transfer_row("S2", "S2", 1)])
    planner = LocalGtfsSchedulePlanner(gtfs_directory)

    journey = planner.find_earliest_journey(
        origin_stop_id="S1",
        destination_stop_id="S3",
        service_date=SERVICE_DATE,
        departure_after="08:00:00",
    )

    assert journey is not None
    assert journey.transfers[0].transfer_type == 1
    assert journey.transfers[0].min_transfer_time_seconds is None
    assert journey.transfers[0].scheduled_gap_seconds >= 0


def test_station_level_transfer_rule_expands_to_its_platform(tmp_path: Path) -> None:
    gtfs_directory = _write_gtfs(tmp_path / "GTFS")
    _write_transfers(
        gtfs_directory,
        [_transfer_row("DEST_STATION", "DEST_STATION", 2, 300)],
    )
    planner = LocalGtfsSchedulePlanner(gtfs_directory)

    journey = planner.find_earliest_journey(
        origin_stop_id="S1",
        destination_stop_id="S3",
        service_date=SERVICE_DATE,
        departure_after="08:00:00",
    )

    assert journey is not None
    assert journey.transfers[0].from_stop_id == "S2"
    assert journey.transfers[0].to_stop_id == "S2"


def test_trip_specific_rule_overrides_route_and_generic_rules(tmp_path: Path) -> None:
    gtfs_directory = _write_gtfs(tmp_path / "GTFS")
    _write_transfers(
        gtfs_directory,
        [
            _transfer_row("S2", "S2", 2, 1200),
            _transfer_row("S2", "S2", 3, from_route_id="R1", to_route_id="R1"),
            _transfer_row(
                "S2",
                "S2",
                2,
                300,
                from_trip_id="before",
                to_trip_id="transfer-leg",
            ),
        ],
    )
    planner = LocalGtfsSchedulePlanner(gtfs_directory)

    journey = planner.find_earliest_journey(
        origin_stop_id="S1",
        destination_stop_id="S3",
        service_date=SERVICE_DATE,
        departure_after="08:00:00",
    )

    assert journey is not None
    assert journey.legs[0].trip_id == "before"
    assert journey.transfers[0].transfer_type == 2
    assert journey.transfers[0].min_transfer_time_seconds == 300


def test_route_search_supports_more_than_one_explicit_transfer(tmp_path: Path) -> None:
    gtfs_directory = _write_gtfs(tmp_path / "GTFS")
    _write_transfers(
        gtfs_directory,
        [
            _transfer_row("S2", "S2", 2, 300),
            _transfer_row("S3", "S3", 2, 300),
        ],
    )
    planner = LocalGtfsSchedulePlanner(gtfs_directory)

    journey = planner.find_earliest_journey(
        origin_stop_id="S1",
        destination_stop_id="S4",
        service_date=SERVICE_DATE,
        departure_after="08:00:00",
    )

    assert journey is not None
    assert len(journey.legs) == 3
    assert journey.legs[0].trip_id in {"before", "added"}
    assert journey.legs[1].trip_id == "transfer-leg"
    assert journey.legs[2].trip_id == "transfer-leg-2"
    assert len(journey.transfers) == 2
    assert journey.arrival_time == "09:45:00"


def test_parent_station_is_rejected_until_internal_walk_is_modeled(tmp_path: Path) -> None:
    planner = LocalGtfsSchedulePlanner(_write_gtfs(tmp_path / "GTFS"))

    with pytest.raises(UnsupportedStopLocation, match="platform stop"):
        planner.find_direct_journeys(
            origin_stop_id="STATION",
            destination_stop_id="S2",
            service_date=SERVICE_DATE,
            departure_after="08:00:00",
        )


def test_invalid_time_is_rejected_without_using_a_static_fallback(tmp_path: Path) -> None:
    planner = LocalGtfsSchedulePlanner(_write_gtfs(tmp_path / "GTFS"))

    with pytest.raises(ValueError, match="GTFS time"):
        planner.find_direct_journeys(
            origin_stop_id="S1",
            destination_stop_id="S2",
            service_date=SERVICE_DATE,
            departure_after="8:99:00",
        )


def test_stop_time_index_is_reused_across_direct_queries(tmp_path: Path) -> None:
    planner = LocalGtfsSchedulePlanner(_write_gtfs(tmp_path / "GTFS"))

    first = planner.find_direct_journeys(
        origin_stop_id="S1",
        destination_stop_id="S2",
        service_date=SERVICE_DATE,
        departure_after="08:24:00",
    )
    cached_index = planner._stop_time_index
    second = planner.find_direct_journeys(
        origin_stop_id="S1",
        destination_stop_id="S2",
        service_date=SERVICE_DATE,
        departure_after="08:24:00",
    )

    assert cached_index is not None
    assert planner._stop_time_index is cached_index
    assert second == first


def test_looping_trip_returns_only_its_best_direct_segment(tmp_path: Path) -> None:
    gtfs_directory = _write_gtfs(tmp_path / "GTFS")
    with (gtfs_directory / "trips.txt").open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["route_id", "service_id", "trip_id", "trip_headsign", "direction_id"],
        )
        writer.writerow(
            {"route_id": "R1", "service_id": "WEEKDAY", "trip_id": "loop", "trip_headsign": "Loop", "direction_id": "0"}
        )
    with (gtfs_directory / "stop_times.txt").open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time", "pickup_type", "drop_off_type"],
        )
        writer.writerows(
            [
                {"trip_id": "loop", "stop_id": "S1", "stop_sequence": "1", "arrival_time": "08:26:00", "departure_time": "08:26:00", "pickup_type": "0", "drop_off_type": "0"},
                {"trip_id": "loop", "stop_id": "S2", "stop_sequence": "2", "arrival_time": "08:40:00", "departure_time": "08:40:00", "pickup_type": "0", "drop_off_type": "0"},
                {"trip_id": "loop", "stop_id": "S1", "stop_sequence": "3", "arrival_time": "08:50:00", "departure_time": "08:50:00", "pickup_type": "0", "drop_off_type": "0"},
                {"trip_id": "loop", "stop_id": "S2", "stop_sequence": "4", "arrival_time": "09:00:00", "departure_time": "09:00:00", "pickup_type": "0", "drop_off_type": "0"},
            ]
        )
    planner = LocalGtfsSchedulePlanner(gtfs_directory)

    journeys = planner.find_direct_journeys(
        origin_stop_id="S1",
        destination_stop_id="S2",
        service_date=SERVICE_DATE,
        departure_after="08:24:00",
    )
    loop_journeys = [journey for journey in journeys if journey.trip_id == "loop"]

    assert len(loop_journeys) == 1
    assert loop_journeys[0].departure_time == "08:26:00"
    assert loop_journeys[0].arrival_time == "08:40:00"


def test_route_specific_prohibition_overrides_generic_timed_rule(tmp_path: Path) -> None:
    gtfs_directory = _write_gtfs(tmp_path / "GTFS")
    _write_transfers(
        gtfs_directory,
        [
            _transfer_row("S2", "S2", 1, 240),
            _transfer_row("S2", "S2", 3, from_route_id="R1", to_route_id="R1"),
        ],
    )
    planner = LocalGtfsSchedulePlanner(gtfs_directory)

    journey = planner.find_earliest_journey(
        origin_stop_id="S1",
        destination_stop_id="S3",
        service_date=SERVICE_DATE,
        departure_after="08:00:00",
    )

    assert journey is not None
    assert journey.legs[0].trip_id == "added"
    assert journey.transfers[0].transfer_type == 1
    assert journey.transfers[0].scheduled_gap_seconds == 300


def test_missing_minimum_time_on_type_two_rule_fails_closed(tmp_path: Path) -> None:
    gtfs_directory = _write_gtfs(tmp_path / "GTFS")
    _write_transfers(gtfs_directory, [_transfer_row("S2", "S2", 2)])

    with pytest.raises(LocalGtfsDataError, match="requires min_transfer_time"):
        LocalGtfsSchedulePlanner(gtfs_directory)


def test_unsorted_trip_rows_fail_closed_instead_of_building_a_wrong_index(
    tmp_path: Path,
) -> None:
    gtfs_directory = _write_gtfs(tmp_path / "GTFS")
    stop_times_path = gtfs_directory / "stop_times.txt"
    with stop_times_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    trip_rows: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        trip_rows.setdefault(row["trip_id"], []).append(row)
    reordered_rows = [
        row
        for trip_id in reversed(tuple(trip_rows))
        for row in trip_rows[trip_id]
    ]
    _write_csv(
        stop_times_path,
        [
            "trip_id",
            "stop_id",
            "stop_sequence",
            "arrival_time",
            "departure_time",
            "pickup_type",
            "drop_off_type",
        ],
        reordered_rows,
    )
    planner = LocalGtfsSchedulePlanner(gtfs_directory)

    with pytest.raises(LocalGtfsDataError, match="grouped in trips.txt order"):
        planner.find_earliest_journey(
            origin_stop_id="S1",
            destination_stop_id="S3",
            service_date=SERVICE_DATE,
            departure_after="08:00:00",
        )


def test_pathway_only_transfer_uses_shortest_directed_timed_path(tmp_path: Path) -> None:
    gtfs_directory = _write_gtfs(tmp_path / "GTFS")
    _write_pathways(
        gtfs_directory,
        [
            _pathway_row("slow-1", "S2", "PATH_NODE", 30),
            _pathway_row("slow-2", "PATH_NODE", "S5", 45),
            _pathway_row("fast-1", "S2", "PATH_NODE_FAST", 10),
            _pathway_row("fast-2", "PATH_NODE_FAST", "S5", 10),
        ],
    )
    planner = LocalGtfsSchedulePlanner(gtfs_directory)

    journey = planner.find_earliest_journey(
        origin_stop_id="S1",
        destination_stop_id="S4",
        service_date=SERVICE_DATE,
        departure_after="08:00:00",
    )

    assert journey is not None
    assert [leg.trip_id for leg in journey.legs] == ["before", "pathway-leg"]
    assert journey.transfers[0].transfer_type is None
    assert journey.transfers[0].pathway_traversal_seconds == 20
    assert journey.transfers[0].pathway_stop_ids == (
        "S2",
        "PATH_NODE_FAST",
        "S5",
    )
    assert journey.transfers[0].pathway_ids == ("fast-1", "fast-2")


def test_explicit_transfer_minimum_and_path_time_use_the_stricter_bound(
    tmp_path: Path,
) -> None:
    gtfs_directory = _write_gtfs(tmp_path / "GTFS")
    _write_transfers(
        gtfs_directory,
        [_transfer_row("S2", "S5", 2, 100)],
    )
    _write_pathways(
        gtfs_directory,
        [
            _pathway_row("fast-1", "S2", "PATH_NODE_FAST", 10),
            _pathway_row("fast-2", "PATH_NODE_FAST", "S5", 10),
        ],
    )
    planner = LocalGtfsSchedulePlanner(gtfs_directory)

    journey = planner.find_earliest_journey(
        origin_stop_id="S1",
        destination_stop_id="S4",
        service_date=SERVICE_DATE,
        departure_after="08:00:00",
    )

    assert journey is not None
    assert journey.legs[0].trip_id == "before"
    assert journey.transfers[0].min_transfer_time_seconds == 100
    assert journey.transfers[0].pathway_traversal_seconds == 20
    assert journey.transfers[0].scheduled_gap_seconds == 100


def test_unidirectional_pathway_is_not_reversed_implicitly(tmp_path: Path) -> None:
    gtfs_directory = _write_gtfs(tmp_path / "GTFS")
    _write_pathways(
        gtfs_directory,
        [
            _pathway_row("one-way-1", "S2", "PATH_NODE", 30),
            _pathway_row("one-way-2", "PATH_NODE", "S5", 45),
        ],
    )
    planner = LocalGtfsSchedulePlanner(gtfs_directory)

    journey = planner.find_earliest_journey(
        origin_stop_id="S4",
        destination_stop_id="S3",
        service_date=SERVICE_DATE,
        departure_after="08:00:00",
    )

    assert journey is None


def test_bidirectional_pathway_supports_reverse_station_transfer(tmp_path: Path) -> None:
    gtfs_directory = _write_gtfs(tmp_path / "GTFS")
    _write_pathways(
        gtfs_directory,
        [
            _pathway_row("two-way-1", "S2", "PATH_NODE", 30, is_bidirectional=1),
            _pathway_row("two-way-2", "PATH_NODE", "S5", 45, is_bidirectional=1),
        ],
    )
    planner = LocalGtfsSchedulePlanner(gtfs_directory)

    journey = planner.find_earliest_journey(
        origin_stop_id="S4",
        destination_stop_id="S3",
        service_date=SERVICE_DATE,
        departure_after="08:00:00",
    )

    assert journey is not None
    assert [leg.trip_id for leg in journey.legs] == [
        "pathway-incoming",
        "transfer-leg",
    ]
    assert journey.transfers[0].pathway_traversal_seconds == 75
    assert journey.transfers[0].pathway_stop_ids == (
        "S5",
        "PATH_NODE",
        "S2",
    )


def test_missing_pathway_traversal_time_is_not_guessed(tmp_path: Path) -> None:
    gtfs_directory = _write_gtfs(tmp_path / "GTFS")
    _write_pathways(
        gtfs_directory,
        [
            _pathway_row("timed", "S2", "PATH_NODE", 30),
            _pathway_row("untimed", "PATH_NODE", "S5", None),
        ],
    )
    planner = LocalGtfsSchedulePlanner(gtfs_directory)

    journey = planner.find_earliest_journey(
        origin_stop_id="S1",
        destination_stop_id="S4",
        service_date=SERVICE_DATE,
        departure_after="08:00:00",
    )

    assert journey is None


def test_prohibited_transfer_rule_cannot_be_bypassed_by_a_pathway(
    tmp_path: Path,
) -> None:
    gtfs_directory = _write_gtfs(tmp_path / "GTFS")
    _write_transfers(gtfs_directory, [_transfer_row("S2", "S5", 3)])
    _write_pathways(
        gtfs_directory,
        [
            _pathway_row("fast-1", "S2", "PATH_NODE_FAST", 10),
            _pathway_row("fast-2", "PATH_NODE_FAST", "S5", 10),
        ],
    )
    planner = LocalGtfsSchedulePlanner(gtfs_directory)

    journey = planner.find_earliest_journey(
        origin_stop_id="S1",
        destination_stop_id="S4",
        service_date=SERVICE_DATE,
        departure_after="08:00:00",
    )

    assert journey is None


def test_pathway_endpoint_marked_stop_access_one_fails_closed(tmp_path: Path) -> None:
    gtfs_directory = _write_gtfs(tmp_path / "GTFS")
    stops_path = gtfs_directory / "stops.txt"
    with stops_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        row["stop_access"] = "1" if row["stop_id"] == "PATH_NODE" else "0"
    _write_csv(
        stops_path,
        ["stop_id", "stop_name", "location_type", "parent_station", "stop_access"],
        rows,
    )
    _write_pathways(
        gtfs_directory,
        [_pathway_row("blocked-node", "S2", "PATH_NODE", 30)],
    )

    with pytest.raises(LocalGtfsDataError, match="stop_access=1"):
        LocalGtfsSchedulePlanner(gtfs_directory)
