from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from bvg_radar.realtime.contracts import (
    EstimatedVehiclePosition,
    VehiclePositionSnapshot,
)


def test_schedule_only_position_does_not_claim_an_observed_zero_delay() -> None:
    position = EstimatedVehiclePosition(
        entity_id="entity-schedule-only",
        trip_id="trip-42",
        route_id="route-7",
        shape_id="shape-42",
        previous_stop_id="stop-1",
        next_stop_id="stop-2",
        delay_seconds=None,
        estimated_next_arrival=datetime(2026, 7, 19, 10, 5, tzinfo=timezone.utc),
        longitude=13.401,
        latitude=52.501,
        bearing_degrees=91.5,
        speed_mps=8.2,
        observed_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc),
        timing_source="schedule_only",
        feed_timestamp=datetime(2026, 7, 19, 9, 59, 45, tzinfo=timezone.utc),
        trip_update_timestamp=None,
        service_date=date(2026, 7, 19),
        is_estimated=True,
        position_status="estimated_from_trip_update",
    )

    event = position.to_websocket_event()

    assert event["delay_seconds"] is None
    assert event["timing_source"] == "schedule_only"
    assert event["feed_timestamp"] == "2026-07-19T09:59:45Z"
    assert event["trip_update_timestamp"] is None
    assert event["service_date"] == "2026-07-19"
    assert event["is_estimated"] is True
    assert event["position_status"] == "estimated_from_trip_update"


def test_schedule_only_position_rejects_a_numeric_delay() -> None:
    with pytest.raises(ValueError, match="schedule_only"):
        EstimatedVehiclePosition(
            entity_id="entity-invalid",
            trip_id="trip-42",
            route_id="route-7",
            shape_id="shape-42",
            previous_stop_id="stop-1",
            next_stop_id="stop-2",
            delay_seconds=0,
            estimated_next_arrival=datetime(
                2026, 7, 19, 10, 5, tzinfo=timezone.utc
            ),
            longitude=13.401,
            latitude=52.501,
            bearing_degrees=91.5,
            speed_mps=8.2,
            observed_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc),
            timing_source="schedule_only",
            feed_timestamp=None,
            trip_update_timestamp=None,
            service_date=date(2026, 7, 19),
            is_estimated=True,
            position_status="estimated_from_trip_update",
        )


def test_realtime_timing_source_requires_an_observed_delay() -> None:
    position = _realtime_position()

    with pytest.raises(ValueError, match="realtime timing"):
        replace(position, delay_seconds=None)


def test_realtime_timing_rejects_a_non_integer_delay() -> None:
    with pytest.raises(ValueError, match="delay_seconds must be an integer"):
        replace(_realtime_position(), delay_seconds="75")  # type: ignore[arg-type]


def test_position_rejects_an_unknown_timing_source() -> None:
    position = _realtime_position()

    with pytest.raises(ValueError, match="timing_source"):
        replace(position, timing_source="inferred_punctuality")  # type: ignore[arg-type]


def test_position_contract_rejects_an_unknown_position_status() -> None:
    with pytest.raises(ValueError, match="position_status"):
        replace(_realtime_position(), position_status="gps_observed")


def test_position_contract_rejects_a_non_estimated_row() -> None:
    position = _realtime_position()

    with pytest.raises(ValueError, match="is_estimated"):
        replace(position, is_estimated=False)


def _realtime_position() -> EstimatedVehiclePosition:
    return EstimatedVehiclePosition(
        entity_id="entity-42",
        trip_id="trip-42",
        route_id="route-7",
        shape_id="shape-42",
        previous_stop_id="stop-1",
        next_stop_id="stop-2",
        delay_seconds=75,
        estimated_next_arrival=datetime(2026, 7, 19, 10, 5, tzinfo=timezone.utc),
        longitude=13.401,
        latitude=52.501,
        bearing_degrees=91.5,
        speed_mps=8.2,
        observed_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc),
        timing_source="realtime_delay",
        feed_timestamp=None,
        trip_update_timestamp=None,
        service_date=date(2026, 7, 19),
        is_estimated=True,
        position_status="estimated_from_trip_update",
    )


def test_estimated_vehicle_position_defaults_vehicle_category_to_none() -> None:
    position = _realtime_position()

    assert position.vehicle_category is None
    assert position.route_short_name is None
    assert position.to_websocket_event()["vehicle_category"] is None
    assert position.to_websocket_event()["route_short_name"] is None


def test_vehicle_position_snapshot_serializes_one_versioned_cycle() -> None:
    feed_timestamp = datetime(2026, 7, 19, 9, 59, 45, tzinfo=timezone.utc)
    position = replace(_realtime_position(), feed_timestamp=feed_timestamp)
    snapshot = VehiclePositionSnapshot(
        cycle_id="cycle-20260719-100000",
        feed_timestamp=feed_timestamp,
        observed_at=position.observed_at,
        positions=(position,),
        trip_updates_received=2,
        positions_suppressed=1,
    )

    event = snapshot.to_websocket_event()

    assert event == {
        "type": "vehicle_position_snapshot",
        "schema_version": 1,
        "cycle_id": "cycle-20260719-100000",
        "feed_timestamp": "2026-07-19T09:59:45Z",
        "observed_at": "2026-07-19T10:00:00Z",
        "positions": [position.to_websocket_event()],
        "statistics": {
            "trip_updates_received": 2,
            "positions_estimated": 1,
            "positions_suppressed": 1,
        },
    }


def test_vehicle_position_snapshot_rejects_inconsistent_statistics() -> None:
    position = _realtime_position()

    with pytest.raises(ValueError, match="statistics"):
        VehiclePositionSnapshot(
            cycle_id="cycle-1",
            feed_timestamp=None,
            observed_at=position.observed_at,
            positions=(position,),
            trip_updates_received=1,
            positions_suppressed=1,
        )


def test_vehicle_position_snapshot_rejects_duplicate_trip_ids() -> None:
    position = _realtime_position()

    with pytest.raises(ValueError, match="duplicate trip_id"):
        VehiclePositionSnapshot(
            cycle_id="cycle-1",
            feed_timestamp=None,
            observed_at=position.observed_at,
            positions=(position, position),
            trip_updates_received=2,
            positions_suppressed=0,
        )


@pytest.mark.parametrize(
    "position",
    [
        replace(
            _realtime_position(),
            feed_timestamp=datetime(2026, 7, 19, 9, 59, tzinfo=timezone.utc),
        ),
        replace(
            _realtime_position(),
            observed_at=datetime(2026, 7, 19, 10, 1, tzinfo=timezone.utc),
        ),
    ],
)
def test_vehicle_position_snapshot_rejects_position_provenance_mismatch(
    position: EstimatedVehiclePosition,
) -> None:
    with pytest.raises(ValueError, match="snapshot provenance"):
        VehiclePositionSnapshot(
            cycle_id="cycle-1",
            feed_timestamp=None,
            observed_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc),
            positions=(position,),
            trip_updates_received=1,
            positions_suppressed=0,
        )


@pytest.mark.parametrize("cycle_id", ["", "   "])
def test_vehicle_position_snapshot_rejects_an_empty_cycle_id(cycle_id: str) -> None:
    with pytest.raises(ValueError, match="cycle_id"):
        VehiclePositionSnapshot(
            cycle_id=cycle_id,
            feed_timestamp=None,
            observed_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc),
            positions=(),
            trip_updates_received=0,
            positions_suppressed=0,
        )


@pytest.mark.parametrize(
    ("trip_updates_received", "positions_suppressed"),
    [(-1, -1), (True, True), (0, -1), (False, 0)],
)
def test_vehicle_position_snapshot_rejects_non_strict_counts(
    trip_updates_received: int,
    positions_suppressed: int,
) -> None:
    with pytest.raises(ValueError, match="statistics"):
        VehiclePositionSnapshot(
            cycle_id="cycle-1",
            feed_timestamp=None,
            observed_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc),
            positions=(),
            trip_updates_received=trip_updates_received,
            positions_suppressed=positions_suppressed,
        )


@pytest.mark.parametrize(
    ("feed_timestamp", "observed_at"),
    [
        (None, datetime(2026, 7, 19, 10, 0)),
        (
            datetime(2026, 7, 19, 9, 59),
            datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc),
        ),
    ],
)
def test_vehicle_position_snapshot_rejects_naive_timestamps(
    feed_timestamp: datetime | None,
    observed_at: datetime,
) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        VehiclePositionSnapshot(
            cycle_id="cycle-1",
            feed_timestamp=feed_timestamp,
            observed_at=observed_at,
            positions=(),
            trip_updates_received=0,
            positions_suppressed=0,
        )
