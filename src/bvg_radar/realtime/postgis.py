import json
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Protocol, cast

from .contracts import EstimatedVehiclePosition, TimingSource
from .models import TripUpdate
from .vehicle_category import classify_berlin_vehicle

ESTIMATE_TRIP_POSITION_SQL = """
SELECT
    trip_id,
    route_id,
    shape_id,
    previous_stop_id,
    next_stop_id,
    delay_seconds,
    timing_source,
    estimated_next_arrival,
    longitude,
    latitude,
    bearing_degrees,
    speed_mps,
    is_estimated,
    position_status
FROM gtfs.estimate_trip_position($1::TEXT, $2::DATE, $3::TIMESTAMPTZ, $4::JSONB);
"""

ESTIMATE_TRIP_POSITIONS_BATCH_SQL = """
SELECT
    input_index,
    trip_id,
    route_id,
    shape_id,
    previous_stop_id,
    next_stop_id,
    delay_seconds,
    timing_source,
    estimated_next_arrival,
    longitude,
    latitude,
    bearing_degrees,
    speed_mps,
    is_estimated,
    position_status,
    route_type,
    route_short_name
FROM gtfs.estimate_trip_positions_batch($1::TIMESTAMPTZ, $2::JSONB)
ORDER BY input_index;
"""

DEFAULT_BATCH_SIZE = 256


class _QueryConnection(Protocol):
    async def fetchrow(self, query: str, *arguments: object) -> object | None: ...

    async def fetch(self, query: str, *arguments: object) -> Sequence[object]: ...


class PostgisTripPositionEstimator:
    """Database adapter for the server-only PostGIS interpolation function."""

    def __init__(
        self,
        connection: _QueryConnection,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self._connection = connection
        self._batch_size = batch_size

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

        delay_seconds = row["delay_seconds"]
        trip_update_timestamp = (
            None
            if update.trip_update_timestamp is None
            else datetime.fromtimestamp(update.trip_update_timestamp, timezone.utc)
        )
        return EstimatedVehiclePosition(
            entity_id=update.entity_id,
            trip_id=str(row["trip_id"]),
            route_id=str(row["route_id"]),
            shape_id=str(row["shape_id"]),
            previous_stop_id=str(row["previous_stop_id"]),
            next_stop_id=str(row["next_stop_id"]),
            delay_seconds=cast(int | None, delay_seconds),
            estimated_next_arrival=row["estimated_next_arrival"],
            longitude=float(row["longitude"]),
            latitude=float(row["latitude"]),
            bearing_degrees=float(row["bearing_degrees"]),
            speed_mps=float(row["speed_mps"]),
            observed_at=observed_at,
            timing_source=cast(TimingSource, str(row["timing_source"])),
            feed_timestamp=None,
            trip_update_timestamp=trip_update_timestamp,
            service_date=update.service_date,
            is_estimated=cast(bool, row["is_estimated"]),
            position_status=str(row["position_status"]),
        )

    async def estimate_many(
        self,
        updates: Sequence[TripUpdate],
        observed_at: datetime,
        max_positions: int | None = None,
    ) -> tuple[EstimatedVehiclePosition, ...]:
        """Estimate in bounded database batches while preserving input order."""
        if max_positions is not None and max_positions <= 0:
            raise ValueError("max_positions must be positive when provided")
        results: list[EstimatedVehiclePosition] = []
        for offset in range(0, len(updates), self._batch_size):
            chunk = updates[offset : offset + self._batch_size]
            payload = []
            for update in chunk:
                if not update.is_static_schedule_matchable:
                    raise ValueError(
                        "estimate_many requires static-schedule-matchable updates"
                    )
                payload.append(
                    {
                        "trip_id": update.trip_id,
                        "service_date": update.service_date.isoformat(),
                        "stop_time_updates": [
                            item.to_estimator_payload()
                            for item in update.stop_time_updates
                        ],
                    }
                )
            rows = await self._connection.fetch(
                ESTIMATE_TRIP_POSITIONS_BATCH_SQL,
                observed_at,
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
            )
            indexed_rows: list[tuple[int, object]] = []
            seen_input_indexes: set[int] = set()
            for row in rows:
                input_index = row["input_index"]
                if type(input_index) is not int or not 0 <= input_index < len(chunk):
                    raise ValueError("batch estimator returned an invalid input_index")
                if input_index in seen_input_indexes:
                    raise ValueError("batch estimator returned a duplicate input_index")
                seen_input_indexes.add(input_index)
                indexed_rows.append((input_index, row))

            for input_index, row in sorted(indexed_rows, key=lambda item: item[0]):
                update = chunk[input_index]
                returned_trip_id = row["trip_id"]
                if (
                    type(returned_trip_id) is not str
                    or returned_trip_id != update.trip_id
                ):
                    raise ValueError("batch estimator returned a mismatched trip_id")
                trip_update_timestamp = (
                    None
                    if update.trip_update_timestamp is None
                    else datetime.fromtimestamp(
                        update.trip_update_timestamp,
                        timezone.utc,
                    )
                )
                route_short_name = (
                    None
                    if row["route_short_name"] is None
                    else str(row["route_short_name"])
                )
                results.append(
                    EstimatedVehiclePosition(
                        entity_id=update.entity_id,
                        trip_id=returned_trip_id,
                        route_id=str(row["route_id"]),
                        shape_id=str(row["shape_id"]),
                        previous_stop_id=str(row["previous_stop_id"]),
                        next_stop_id=str(row["next_stop_id"]),
                        delay_seconds=cast(int | None, row["delay_seconds"]),
                        estimated_next_arrival=row["estimated_next_arrival"],
                        longitude=float(row["longitude"]),
                        latitude=float(row["latitude"]),
                        bearing_degrees=float(row["bearing_degrees"]),
                        speed_mps=float(row["speed_mps"]),
                        observed_at=observed_at,
                        timing_source=cast(
                            TimingSource,
                            str(row["timing_source"]),
                        ),
                        feed_timestamp=None,
                        trip_update_timestamp=trip_update_timestamp,
                        service_date=update.service_date,
                        is_estimated=cast(bool, row["is_estimated"]),
                        position_status=str(row["position_status"]),
                        vehicle_category=classify_berlin_vehicle(
                            cast(int, row["route_type"]),
                            route_short_name,
                        ),
                        route_short_name=route_short_name,
                    )
                )
                if max_positions is not None and len(results) >= max_positions:
                    break
            if max_positions is not None and len(results) >= max_positions:
                break
        return tuple(results)
