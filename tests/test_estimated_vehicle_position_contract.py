from datetime import datetime, timezone

from bvg_radar.realtime.contracts import EstimatedVehiclePosition


def test_estimated_vehicle_position_defaults_vehicle_category_to_none() -> None:
    position = EstimatedVehiclePosition(
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
    )

    assert position.vehicle_category is None
    assert position.route_short_name is None
    assert position.to_websocket_event()["vehicle_category"] is None
    assert position.to_websocket_event()["route_short_name"] is None
