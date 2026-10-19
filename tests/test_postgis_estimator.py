import asyncio
from datetime import date, datetime, timezone

import pytest

from bvg_radar.realtime.models import StopTimeUpdate, TripUpdate
from bvg_radar.realtime.postgis import PostgisTripPositionEstimator


class RecordingConnection:
    def __init__(self, row: dict[str, object] | None = None) -> None:
        self.arguments: tuple[object, ...] | None = None
        self.query: str | None = None
        self.row = row or {
            "trip_id": "trip-42",
            "route_id": "route-7",
            "shape_id": "shape-42",
            "previous_stop_id": "stop-1",
            "next_stop_id": "stop-2",
            "delay_seconds": 90,
            "timing_source": "realtime_delay",
            "estimated_next_arrival": datetime(
                2026, 7, 19, 10, 5, tzinfo=timezone.utc
            ),
            "longitude": 13.401,
            "latitude": 52.501,
            "bearing_degrees": 91.5,
            "speed_mps": 8.2,
            "is_estimated": True,
            "position_status": "estimated_from_trip_update",
        }

    async def fetchrow(self, query: str, *arguments: object) -> dict[str, object]:
        self.query = query
        self.arguments = arguments
        return self.row


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
    assert result.delay_seconds == 90
    assert result.timing_source == "realtime_delay"
    assert result.trip_update_timestamp == datetime.fromtimestamp(
        update.trip_update_timestamp, timezone.utc
    )
    assert result.service_date == date(2026, 7, 19)
    assert result.is_estimated is True
    assert result.position_status == "estimated_from_trip_update"
    assert connection.query is not None
    assert "timing_source" in connection.query
    assert connection.arguments == (
        "trip-42",
        date(2026, 7, 19),
        observed_at,
        '[{"arrival_delay_seconds":90,"arrival_time":1784457900,"stop_id":"stop-2","stop_sequence":2}]',
    )


def test_postgis_estimator_preserves_schedule_only_without_observed_delay() -> None:
    connection = RecordingConnection(
        {
            "trip_id": "trip-42",
            "route_id": "route-7",
            "shape_id": "shape-42",
            "previous_stop_id": "stop-1",
            "next_stop_id": "stop-2",
            "delay_seconds": None,
            "timing_source": "schedule_only",
            "estimated_next_arrival": datetime(
                2026, 7, 19, 10, 5, tzinfo=timezone.utc
            ),
            "longitude": 13.401,
            "latitude": 52.501,
            "bearing_degrees": 91.5,
            "speed_mps": 8.2,
            "is_estimated": True,
            "position_status": "estimated_from_trip_update",
        }
    )
    estimator = PostgisTripPositionEstimator(connection)
    update = TripUpdate(
        entity_id="entity-42",
        trip_id="trip-42",
        route_id="route-7",
        service_date=date(2026, 7, 19),
        trip_update_timestamp=None,
        stop_time_updates=(),
    )
    observed_at = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)

    result = asyncio.run(estimator.estimate(update, observed_at))

    assert result is not None
    assert result.delay_seconds is None
    assert result.timing_source == "schedule_only"
    assert result.trip_update_timestamp is None


def test_postgis_estimator_rejects_a_numeric_string_delay() -> None:
    row = dict(RecordingConnection().row)
    row["delay_seconds"] = "90"
    estimator = PostgisTripPositionEstimator(RecordingConnection(row))
    update = TripUpdate(
        entity_id="entity-42",
        trip_id="trip-42",
        route_id="route-7",
        service_date=date(2026, 7, 19),
        trip_update_timestamp=None,
        stop_time_updates=(),
    )

    with pytest.raises(ValueError, match="delay_seconds"):
        asyncio.run(
            estimator.estimate(
                update,
                datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc),
            )
        )


def test_postgis_estimator_rejects_a_truthy_non_boolean_estimation_flag() -> None:
    row = dict(RecordingConnection().row)
    row["is_estimated"] = "false"
    estimator = PostgisTripPositionEstimator(RecordingConnection(row))
    update = TripUpdate(
        entity_id="entity-42",
        trip_id="trip-42",
        route_id="route-7",
        service_date=date(2026, 7, 19),
        trip_update_timestamp=None,
        stop_time_updates=(),
    )

    with pytest.raises(ValueError, match="is_estimated"):
        asyncio.run(
            estimator.estimate(
                update,
                datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc),
            )
        )
