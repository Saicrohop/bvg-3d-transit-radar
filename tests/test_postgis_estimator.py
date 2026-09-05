import asyncio
from datetime import date, datetime, timezone

from bvg_radar.realtime.models import StopTimeUpdate, TripUpdate
from bvg_radar.realtime.postgis import PostgisTripPositionEstimator


class RecordingConnection:
    def __init__(self) -> None:
        self.arguments: tuple[object, ...] | None = None

    async def fetchrow(self, _query: str, *arguments: object) -> dict[str, object]:
        self.arguments = arguments
        return {
            "trip_id": "trip-42",
            "route_id": "route-7",
            "shape_id": "shape-42",
            "previous_stop_id": "stop-1",
            "next_stop_id": "stop-2",
            "delay_seconds": 90,
            "estimated_next_arrival": datetime(2026, 7, 19, 10, 5, tzinfo=timezone.utc),
            "longitude": 13.401,
            "latitude": 52.501,
            "bearing_degrees": 91.5,
            "speed_mps": 8.2,
            "is_estimated": True,
            "position_status": "estimated_from_trip_update",
        }


def test_postgis_estimator_passes_normalized_realtime_values_as_json() -> None:
    connection = RecordingConnection()
    estimator = PostgisTripPositionEstimator(connection)
    update = TripUpdate(
        entity_id="entity-42",
        trip_id="trip-42",
        route_id="route-7",
        service_date=date(2026, 7, 19),
        trip_update_timestamp=1_784_457_600,
        stop_time_updates=(
            StopTimeUpdate(
                stop_sequence=2,
                stop_id="stop-2",
                arrival_time=1_784_457_900,
                arrival_delay_seconds=90,
                departure_time=None,
                departure_delay_seconds=None,
            ),
        ),
    )
    observed_at = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)

    result = asyncio.run(estimator.estimate(update, observed_at))

    assert result is not None
    assert result.entity_id == "entity-42"
    assert result.longitude == 13.401
    assert connection.arguments == (
        "trip-42",
        date(2026, 7, 19),
        observed_at,
        '[{"arrival_delay_seconds":90,"arrival_time":1784457900,"stop_id":"stop-2","stop_sequence":2}]',
    )
