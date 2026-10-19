import asyncio
import json
from datetime import date, datetime, timezone

import pytest

from bvg_radar.realtime.models import StopTimeUpdate, TripUpdate
from bvg_radar.realtime.postgis import PostgisTripPositionEstimator


class RecordingBatchConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch(self, query: str, *arguments: object) -> list[dict[str, object]]:
        self.calls.append((query, arguments))
        updates = json.loads(str(arguments[1]))
        return [
            {
                "input_index": input_index,
                "trip_id": update["trip_id"],
                "route_id": f"route-{update['trip_id']}",
                "shape_id": f"shape-{update['trip_id']}",
                "previous_stop_id": "stop-1",
                "next_stop_id": "stop-2",
                "delay_seconds": None,
                "timing_source": "schedule_only",
                "estimated_next_arrival": datetime(
                    2026, 9, 9, 10, 5, tzinfo=timezone.utc
                ),
                "longitude": 13.4 + input_index / 1000,
                "latitude": 52.5,
                "bearing_degrees": 90.0,
                "speed_mps": 8.0,
                "is_estimated": True,
                "position_status": "estimated_from_trip_update",
                "route_type": 3,
                "route_short_name": "100",
            }
            for input_index, update in enumerate(updates)
        ]


class OutOfOrderBatchConnection(RecordingBatchConnection):
    async def fetch(self, query: str, *arguments: object) -> list[dict[str, object]]:
        rows = await super().fetch(query, *arguments)
        return list(reversed(rows))


class DuplicateIndexBatchConnection(RecordingBatchConnection):
    async def fetch(self, query: str, *arguments: object) -> list[dict[str, object]]:
        rows = await super().fetch(query, *arguments)
        return [*rows, rows[0]]


class MismatchedTripBatchConnection(RecordingBatchConnection):
    async def fetch(self, query: str, *arguments: object) -> list[dict[str, object]]:
        rows = await super().fetch(query, *arguments)
        rows[0]["trip_id"] = "different-trip"
        return rows


def make_update(index: int) -> TripUpdate:
    return TripUpdate(
        entity_id=f"entity-{index}",
        trip_id=f"trip-{index}",
        route_id=f"route-{index}",
        service_date=date(2026, 9, 9),
        trip_update_timestamp=1_789_000_000 + index,
        stop_time_updates=(
            StopTimeUpdate(
                stop_sequence=2,
                stop_id="stop-2",
                arrival_time=None,
                arrival_delay_seconds=index,
                departure_time=None,
                departure_delay_seconds=None,
            ),
        ),
    )


def test_batch_estimator_limits_queries_to_one_per_chunk() -> None:
    connection = RecordingBatchConnection()
    estimator = PostgisTripPositionEstimator(connection, batch_size=2)
    updates = tuple(make_update(index) for index in range(5))
    observed_at = datetime(2026, 9, 9, 10, 0, tzinfo=timezone.utc)

    results = asyncio.run(estimator.estimate_many(updates, observed_at))

    assert len(connection.calls) == 3
    assert [
        len(json.loads(str(arguments[1]))) for _query, arguments in connection.calls
    ] == [2, 2, 1]
    assert [result.entity_id for result in results] == [
        "entity-0",
        "entity-1",
        "entity-2",
        "entity-3",
        "entity-4",
    ]
    assert all(result.vehicle_category == "bus" for result in results)
    assert all(result.route_short_name == "100" for result in results)
    assert "estimate_trip_positions_batch" in connection.calls[0][0]


def test_batch_estimator_stops_after_reaching_the_position_limit() -> None:
    connection = RecordingBatchConnection()
    estimator = PostgisTripPositionEstimator(connection, batch_size=2)
    updates = tuple(make_update(index) for index in range(5))

    results = asyncio.run(
        estimator.estimate_many(
            updates,
            datetime(2026, 9, 9, 10, 0, tzinfo=timezone.utc),
            max_positions=1,
        )
    )

    assert len(connection.calls) == 1
    assert [result.entity_id for result in results] == ["entity-0"]


def test_batch_estimator_preserves_input_order_when_rows_arrive_out_of_order() -> None:
    connection = OutOfOrderBatchConnection()
    estimator = PostgisTripPositionEstimator(connection, batch_size=8)
    updates = tuple(make_update(index) for index in range(3))

    results = asyncio.run(
        estimator.estimate_many(
            updates,
            datetime(2026, 9, 9, 10, 0, tzinfo=timezone.utc),
        )
    )

    assert [result.entity_id for result in results] == [
        "entity-0",
        "entity-1",
        "entity-2",
    ]


def test_batch_estimator_rejects_duplicate_input_indexes() -> None:
    estimator = PostgisTripPositionEstimator(
        DuplicateIndexBatchConnection(),
        batch_size=8,
    )

    with pytest.raises(ValueError, match="duplicate input_index"):
        asyncio.run(
            estimator.estimate_many(
                (make_update(0), make_update(1)),
                datetime(2026, 9, 9, 10, 0, tzinfo=timezone.utc),
            )
        )


def test_batch_estimator_rejects_a_trip_id_mismatch() -> None:
    estimator = PostgisTripPositionEstimator(
        MismatchedTripBatchConnection(),
        batch_size=8,
    )

    with pytest.raises(ValueError, match="trip_id"):
        asyncio.run(
            estimator.estimate_many(
                (make_update(0),),
                datetime(2026, 9, 9, 10, 0, tzinfo=timezone.utc),
            )
        )
