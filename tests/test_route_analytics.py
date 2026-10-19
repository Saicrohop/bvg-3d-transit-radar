from datetime import date, datetime, timezone

from bvg_radar.realtime.contracts import EstimatedVehiclePosition
from bvg_radar.realtime.analytics import aggregate_route_observations


def position(
    *, route_id: str, category: str | None, delay: int | None, trip_id: str
) -> EstimatedVehiclePosition:
    return EstimatedVehiclePosition(
        entity_id=f"entity-{trip_id}",
        trip_id=trip_id,
        route_id=route_id,
        shape_id="shape-1",
        previous_stop_id="stop-1",
        next_stop_id="stop-2",
        delay_seconds=delay,
        estimated_next_arrival=datetime(2026, 10, 18, 12, 5, tzinfo=timezone.utc),
        longitude=13.4,
        latitude=52.5,
        bearing_degrees=90.0,
        speed_mps=8.0,
        observed_at=datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc),
        timing_source="schedule_only" if delay is None else "realtime_delay",
        feed_timestamp=None,
        trip_update_timestamp=None,
        service_date=date(2026, 10, 18),
        is_estimated=True,
        position_status="estimated_from_trip_update",
        vehicle_category=category,
    )


def test_aggregates_samples_by_route_and_category_with_sixty_second_cutoff() -> None:
    rows = aggregate_route_observations(
        (
            position(route_id="bus-100", category="bus", delay=-12, trip_id="1"),
            position(route_id="bus-100", category="bus", delay=60, trip_id="2"),
            position(route_id="bus-100", category="bus", delay=61, trip_id="3"),
            position(route_id="bus-100", category="bus", delay=None, trip_id="4"),
            position(route_id="S2", category="s_bahn", delay=61, trip_id="5"),
            position(route_id="unknown", category=None, delay=0, trip_id="6"),
        )
    )

    assert rows == (
        {
            "route_id": "S2",
            "vehicle_category": "s_bahn",
            "samples": 1,
            "on_time": 0,
            "late": 1,
            "sum_delay_seconds": 61,
        },
        {
            "route_id": "bus-100",
            "vehicle_category": "bus",
            "samples": 3,
            "on_time": 2,
            "late": 1,
            "sum_delay_seconds": 109,
        },
        {
            "route_id": "unknown",
            "vehicle_category": "unknown",
            "samples": 1,
            "on_time": 1,
            "late": 0,
            "sum_delay_seconds": 0,
        },
    )


def test_empty_positions_produce_no_analytics_rows() -> None:
    assert aggregate_route_observations(()) == ()
