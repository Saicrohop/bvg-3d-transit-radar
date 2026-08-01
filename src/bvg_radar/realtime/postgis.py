import json
from datetime import datetime
from typing import Protocol

from .contracts import EstimatedVehiclePosition
from .models import TripUpdate


ESTIMATE_TRIP_POSITION_SQL = """
SELECT
    trip_id,
    route_id,
    shape_id,
    previous_stop_id,
    next_stop_id,
    delay_seconds,
    estimated_next_arrival,
    longitude,
    latitude,
    bearing_degrees,
    speed_mps,
    is_estimated,
    position_status
FROM gtfs.estimate_trip_position($1::TEXT, $2::DATE, $3::TIMESTAMPTZ, $4::JSONB);
"""


class _QueryConnection(Protocol):
    async def fetchrow(self, query: str, *arguments: object) -> object | None: ...


class PostgisTripPositionEstimator:
    """Database adapter for the server-only PostGIS interpolation function."""

    def __init__(self, connection: _QueryConnection) -> None:
        self._connection = connection

    async def estimate(
        self, update: TripUpdate, observed_at: datetime
    ) -> EstimatedVehiclePosition | None:
        stop_time_updates = json.dumps(
            [item.to_estimator_payload() for item in update.stop_time_updates],
            separators=(",", ":"),
            sort_keys=True,
        )
        row = await self._connection.fetchrow(
            ESTIMATE_TRIP_POSITION_SQL,
            update.trip_id,
            update.service_date,
            observed_at,
            stop_time_updates,
        )
        if row is None:
            return None

        return EstimatedVehiclePosition(
            entity_id=update.entity_id,
            trip_id=str(row["trip_id"]),
            route_id=str(row["route_id"]),
            shape_id=str(row["shape_id"]),
            previous_stop_id=str(row["previous_stop_id"]),
            next_stop_id=str(row["next_stop_id"]),
            delay_seconds=int(row["delay_seconds"]),
            estimated_next_arrival=row["estimated_next_arrival"],
            longitude=float(row["longitude"]),
            latitude=float(row["latitude"]),
            bearing_degrees=float(row["bearing_degrees"]),
            speed_mps=float(row["speed_mps"]),
            observed_at=observed_at,
        )
