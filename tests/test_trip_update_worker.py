import asyncio
from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from bvg_radar.realtime.contracts import EstimatedVehiclePosition
from bvg_radar.realtime.models import (
    DeletedFeedEntity,
    GtfsRealtimeFetchResult,
    GtfsRealtimeFetchStatus,
    GtfsRealtimeSnapshot,
    TripScheduleRelationship,
    TripUpdate,
)
from bvg_radar.realtime.worker import (
    AsyncQueuePositionEventPublisher,
    TripUpdateIngestionWorker,
    _position_snapshot_cycle_id,
)


class StaticSource:
    def __init__(
        self,
        updates: tuple[TripUpdate, ...],
        deleted_entities: tuple[DeletedFeedEntity, ...] = (),
    ) -> None:
        self._snapshot = GtfsRealtimeSnapshot(
            feed_timestamp=1_784_457_500,
            trip_updates=updates,
            deleted_entities=deleted_entities,
        )

    async def fetch(self) -> GtfsRealtimeFetchResult:
        return GtfsRealtimeFetchResult(
            status=GtfsRealtimeFetchStatus.UPDATED,
            snapshot=self._snapshot,
        )


class NotModifiedSource:
    async def fetch(self) -> GtfsRealtimeFetchResult:
        return GtfsRealtimeFetchResult(
            status=GtfsRealtimeFetchStatus.NOT_MODIFIED,
            snapshot=None,
        )


class FailsOnceSource(StaticSource):
    def __init__(self, updates: tuple[TripUpdate, ...]) -> None:
        super().__init__(updates)
        self.calls = 0

    async def fetch(self) -> GtfsRealtimeFetchResult:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient VBB failure")
        return await super().fetch()


class MatchingEstimator:
    async def estimate(
        self, update: TripUpdate, observed_at: datetime
    ) -> EstimatedVehiclePosition | None:
        if update.trip_id != "trip-42":
            return None
        return EstimatedVehiclePosition(
            entity_id=update.entity_id,
            trip_id=update.trip_id,
            route_id=update.route_id,
            shape_id="shape-42",
            previous_stop_id="stop-1",
            next_stop_id="stop-2",
            delay_seconds=75,
            estimated_next_arrival=datetime(2026, 7, 19, 10, 5, tzinfo=timezone.utc),
            longitude=13.401,
            latitude=52.501,
            bearing_degrees=91.5,
            speed_mps=8.2,
            observed_at=observed_at,
            timing_source="realtime_delay",
            feed_timestamp=None,
            trip_update_timestamp=datetime.fromtimestamp(
                update.trip_update_timestamp, timezone.utc
            )
            if update.trip_update_timestamp is not None
            else None,
            service_date=update.service_date or date(2026, 7, 19),
            is_estimated=True,
            position_status="estimated_from_trip_update",
        )

    async def estimate_many(
        self,
        updates: tuple[TripUpdate, ...],
        observed_at: datetime,
        max_positions: int | None = None,
    ) -> tuple[EstimatedVehiclePosition, ...]:
        results: list[EstimatedVehiclePosition] = []
        for update in updates:
            result = await self.estimate(update, observed_at)
            if result is not None:
                results.append(result)
            if max_positions is not None and len(results) >= max_positions:
                break
        return tuple(results)


class AllMatchingEstimator:
    async def estimate_many(
        self,
        updates: tuple[TripUpdate, ...],
        observed_at: datetime,
        max_positions: int | None = None,
    ) -> tuple[EstimatedVehiclePosition, ...]:
        template = await MatchingEstimator().estimate(trip_update("trip-42"), observed_at)
        assert template is not None
        estimates = tuple(
            replace(
                template,
                entity_id=update.entity_id,
                trip_id=update.trip_id or "",
                route_id=update.route_id or "",
                trip_update_timestamp=datetime.fromtimestamp(
                    update.trip_update_timestamp, timezone.utc
                )
                if update.trip_update_timestamp is not None
                else None,
                service_date=update.service_date or date(2026, 7, 19),
            )
            for update in updates
        )
        return estimates if max_positions is None else estimates[:max_positions]


class CountingEstimator(MatchingEstimator):
    def __init__(self) -> None:
        self.calls = 0

    async def estimate(
        self, update: TripUpdate, observed_at: datetime
    ) -> EstimatedVehiclePosition | None:
        self.calls += 1
        return await super().estimate(update, observed_at)


class BatchCountingEstimator:
    def __init__(self) -> None:
        self.calls = 0
        self.trip_ids: tuple[str | None, ...] = ()

    async def estimate_many(
        self,
        updates: tuple[TripUpdate, ...],
        observed_at: datetime,
        max_positions: int | None = None,
    ) -> tuple[EstimatedVehiclePosition, ...]:
        self.calls += 1
        self.trip_ids = tuple(update.trip_id for update in updates)
        matching = MatchingEstimator()
        results: list[EstimatedVehiclePosition] = []
        for update in updates:
            result = await matching.estimate(update, observed_at)
            if result is not None:
                results.append(result)
        selected = results if max_positions is None else results[:max_positions]
        return tuple(selected)


class RecordingEstimator(MatchingEstimator):
    def __init__(self, operations: list[str]) -> None:
        self._operations = operations

    async def estimate(
        self, update: TripUpdate, observed_at: datetime
    ) -> EstimatedVehiclePosition | None:
        self._operations.append("estimate")
        return await super().estimate(update, observed_at)


class RecordingPublisher:
    def __init__(self, operations: list[str]) -> None:
        self._operations = operations

    async def publish(self, _event: dict[str, object]) -> None:
        self._operations.append("publish")


def trip_update(
    trip_id: str,
    schedule_relationship: TripScheduleRelationship = (
        TripScheduleRelationship.SCHEDULED
    ),
) -> TripUpdate:
    return TripUpdate(
        entity_id=f"entity-{trip_id}",
        trip_id=trip_id,
        route_id="route-7",
        service_date=date(2026, 7, 19),
        trip_update_timestamp=1_784_457_600,
        stop_time_updates=(),
        schedule_relationship=schedule_relationship,
    )


@pytest.mark.parametrize(
    "schedule_relationship",
    [
        TripScheduleRelationship.ADDED,
        TripScheduleRelationship.UNSCHEDULED,
        TripScheduleRelationship.CANCELED,
        TripScheduleRelationship.REPLACEMENT,
        TripScheduleRelationship.DUPLICATED,
        TripScheduleRelationship.DELETED,
        TripScheduleRelationship.NEW,
        TripScheduleRelationship.UNKNOWN,
    ],
)
def test_worker_does_not_send_non_scheduled_trip_to_estimator(
    schedule_relationship: TripScheduleRelationship,
) -> None:
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    estimator = CountingEstimator()
    worker = TripUpdateIngestionWorker(
        source=StaticSource(
            (
                trip_update(
                    "trip-not-statically-scheduled",
                    schedule_relationship,
                ),
            )
        ),
        estimator=estimator,
        publisher=AsyncQueuePositionEventPublisher(queue),
    )

    result = asyncio.run(
        worker.run_once(observed_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc))
    )

    assert result.trip_updates_received == 1
    assert result.estimated_positions_published == 0
    assert estimator.calls == 0
    snapshot = queue.get_nowait()
    assert snapshot["positions"] == []
    assert snapshot["statistics"] == {
        "trip_updates_received": 1,
        "positions_estimated": 0,
        "positions_suppressed": 1,
    }


def test_worker_sends_all_matchable_updates_to_one_batch_estimator_call() -> None:
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    estimator = BatchCountingEstimator()
    worker = TripUpdateIngestionWorker(
        source=StaticSource(
            (
                trip_update("trip-42"),
                trip_update("trip-42"),
                trip_update("trip-canceled", TripScheduleRelationship.CANCELED),
            )
        ),
        estimator=estimator,
        publisher=AsyncQueuePositionEventPublisher(queue),
    )

    result = asyncio.run(
        worker.run_once(observed_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc))
    )

    assert estimator.calls == 1
    assert estimator.trip_ids == ("trip-42", "trip-42")
    assert result.trip_updates_received == 3
    assert result.estimated_positions_published == 1
    assert queue.qsize() == 1
    snapshot = queue.get_nowait()
    assert snapshot["statistics"] == {
        "trip_updates_received": 3,
        "positions_estimated": 1,
        "positions_suppressed": 2,
    }


def test_worker_publishes_one_versioned_snapshot_per_updated_cycle() -> None:
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    worker = TripUpdateIngestionWorker(
        source=StaticSource((trip_update("trip-42"), trip_update("trip-43"))),
        estimator=AllMatchingEstimator(),
        publisher=AsyncQueuePositionEventPublisher(queue),
    )
    observed_at = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)

    result = asyncio.run(worker.run_once(observed_at=observed_at))

    assert result.estimated_positions_published == 2
    assert result.position_snapshots_published == 1
    assert queue.qsize() == 1
    snapshot = queue.get_nowait()
    assert snapshot["type"] == "vehicle_position_snapshot"
    assert snapshot["schema_version"] == 1
    assert isinstance(snapshot["cycle_id"], str) and snapshot["cycle_id"]
    assert snapshot["feed_timestamp"] == "2026-07-19T10:38:20Z"
    assert snapshot["observed_at"] == "2026-07-19T10:00:00Z"
    assert [position["trip_id"] for position in snapshot["positions"]] == [
        "trip-42",
        "trip-43",
    ]
    assert snapshot["statistics"] == {
        "trip_updates_received": 2,
        "positions_estimated": 2,
        "positions_suppressed": 0,
    }


def test_worker_publishes_an_empty_snapshot_for_a_valid_empty_feed() -> None:
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    worker = TripUpdateIngestionWorker(
        source=StaticSource(()),
        estimator=AllMatchingEstimator(),
        publisher=AsyncQueuePositionEventPublisher(queue),
    )

    result = asyncio.run(
        worker.run_once(observed_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc))
    )

    assert result.fetch_status is GtfsRealtimeFetchStatus.UPDATED
    assert result.estimated_positions_published == 0
    assert result.position_snapshots_published == 1
    snapshot = queue.get_nowait()
    assert snapshot["positions"] == []
    assert snapshot["statistics"] == {
        "trip_updates_received": 0,
        "positions_estimated": 0,
        "positions_suppressed": 0,
    }
    assert queue.empty()


def test_worker_does_not_publish_for_not_modified() -> None:
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    worker = TripUpdateIngestionWorker(
        source=NotModifiedSource(),
        estimator=AllMatchingEstimator(),
        publisher=AsyncQueuePositionEventPublisher(queue),
    )

    result = asyncio.run(
        worker.run_once(observed_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc))
    )

    assert result.fetch_status is GtfsRealtimeFetchStatus.NOT_MODIFIED
    assert result.estimated_positions_published == 0
    assert result.position_snapshots_published == 0
    assert queue.empty()


def test_worker_deduplicates_trip_ids_inside_a_snapshot() -> None:
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    worker = TripUpdateIngestionWorker(
        source=StaticSource((trip_update("trip-42"), trip_update("trip-42"))),
        estimator=AllMatchingEstimator(),
        publisher=AsyncQueuePositionEventPublisher(queue),
    )

    result = asyncio.run(
        worker.run_once(observed_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc))
    )

    assert result.estimated_positions_published == 1
    snapshot = queue.get_nowait()
    assert [position["trip_id"] for position in snapshot["positions"]] == ["trip-42"]
    assert snapshot["statistics"] == {
        "trip_updates_received": 2,
        "positions_estimated": 1,
        "positions_suppressed": 1,
    }


def test_worker_preserves_feed_timestamp_and_deleted_entity_ids() -> None:
    worker = TripUpdateIngestionWorker(
        source=StaticSource(
            updates=(),
            deleted_entities=(DeletedFeedEntity("entity-removed"),),
        ),
        estimator=CountingEstimator(),
        publisher=AsyncQueuePositionEventPublisher(asyncio.Queue()),
    )

    result = asyncio.run(
        worker.run_once(observed_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc))
    )

    assert result.fetch_status is GtfsRealtimeFetchStatus.UPDATED
    assert result.feed_timestamp == 1_784_457_500
    assert result.deleted_entity_ids == ("entity-removed",)


def test_worker_does_not_estimate_scheduled_trip_without_static_identity() -> None:
    incomplete_update = TripUpdate(
        entity_id="entity-incomplete",
        trip_id="trip-incomplete",
        route_id=None,
        service_date=None,
        trip_update_timestamp=1_784_457_600,
        stop_time_updates=(),
    )
    estimator = CountingEstimator()
    worker = TripUpdateIngestionWorker(
        source=StaticSource((incomplete_update,)),
        estimator=estimator,
        publisher=AsyncQueuePositionEventPublisher(asyncio.Queue()),
    )

    result = asyncio.run(
        worker.run_once(observed_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc))
    )

    assert result.trip_updates_received == 1
    assert result.estimated_positions_published == 0
    assert estimator.calls == 0


def test_worker_publishes_estimated_vehicle_position_contract() -> None:
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    worker = TripUpdateIngestionWorker(
        source=StaticSource(
            (trip_update("trip-42"), trip_update("trip-without-segment"))
        ),
        estimator=MatchingEstimator(),
        publisher=AsyncQueuePositionEventPublisher(queue),
    )
    observed_at = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)

    result = asyncio.run(worker.run_once(observed_at=observed_at))

    assert result.trip_updates_received == 2
    assert result.estimated_positions_published == 1
    snapshot = queue.get_nowait()
    assert snapshot["type"] == "vehicle_position_snapshot"
    assert snapshot["schema_version"] == 1
    assert snapshot["statistics"] == {
        "trip_updates_received": 2,
        "positions_estimated": 1,
        "positions_suppressed": 1,
    }
    positions = snapshot["positions"]
    assert isinstance(positions, list) and len(positions) == 1
    event = positions[0]
    assert event == {
        "type": "vehicle_position",
        "source": "trip_update_interpolation",
        "is_estimated": True,
        "position_status": "estimated_from_trip_update",
        "timing_source": "realtime_delay",
        "feed_timestamp": "2026-07-19T10:38:20Z",
        "trip_update_timestamp": "2026-07-19T10:40:00Z",
        "service_date": "2026-07-19",
        "vehicle_category": None,
        "route_short_name": None,
        "entity_id": "entity-trip-42",
        "trip_id": "trip-42",
        "route_id": "route-7",
        "shape_id": "shape-42",
        "previous_stop_id": "stop-1",
        "next_stop_id": "stop-2",
        "delay_seconds": 75,
        "estimated_next_arrival": "2026-07-19T10:05:00Z",
        "longitude": 13.401,
        "latitude": 52.501,
        "bearing_degrees": 91.5,
        "speed_mps": 8.2,
        "observed_at": "2026-07-19T10:00:00Z",
    }


def test_worker_can_measure_serialization_through_an_injected_serializer() -> None:
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    serialized_positions: list[EstimatedVehiclePosition] = []

    def serialize_position(position: EstimatedVehiclePosition) -> dict[str, object]:
        serialized_positions.append(position)
        return {"type": "measured_position"}

    worker = TripUpdateIngestionWorker(
        source=StaticSource((trip_update("trip-42"),)),
        estimator=MatchingEstimator(),
        publisher=AsyncQueuePositionEventPublisher(queue),
        serialize_position=serialize_position,
    )

    result = asyncio.run(
        worker.run_once(observed_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc))
    )

    assert result.estimated_positions_published == 1
    snapshot = queue.get_nowait()
    assert snapshot["type"] == "vehicle_position_snapshot"
    assert snapshot["positions"] == [{"type": "measured_position"}]
    assert len(serialized_positions) == 1
    assert serialized_positions[0].feed_timestamp == datetime(
        2026, 7, 19, 10, 38, 20, tzinfo=timezone.utc
    )


def test_worker_stops_scanning_after_the_requested_position_limit() -> None:
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    estimator = CountingEstimator()
    worker = TripUpdateIngestionWorker(
        source=StaticSource((trip_update("trip-42"), trip_update("trip-42"))),
        estimator=estimator,
        publisher=AsyncQueuePositionEventPublisher(queue),
    )

    result = asyncio.run(
        worker.run_once(
            observed_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc),
            max_positions=1,
        )
    )

    assert result.trip_updates_received == 2
    assert result.estimated_positions_published == 1
    assert estimator.calls == 1
    assert queue.qsize() == 1


def test_worker_finishes_estimation_before_publishing_the_position_batch() -> None:
    operations: list[str] = []
    worker = TripUpdateIngestionWorker(
        source=StaticSource((trip_update("trip-42"), trip_update("trip-42"))),
        estimator=RecordingEstimator(operations),
        publisher=RecordingPublisher(operations),
    )

    result = asyncio.run(
        worker.run_once(observed_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc))
    )

    assert result.estimated_positions_published == 1
    assert operations == ["estimate", "estimate", "publish"]


async def receive_after_a_transient_source_failure() -> tuple[dict[str, object], int]:
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    source = FailsOnceSource((trip_update("trip-42"),))
    worker = TripUpdateIngestionWorker(
        source=source,
        estimator=MatchingEstimator(),
        publisher=AsyncQueuePositionEventPublisher(queue),
    )
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        worker.run_forever(
            interval_seconds=0.001,
            stop_event=stop_event,
            now=lambda: datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc),
        )
    )
    try:
        event = await asyncio.wait_for(queue.get(), timeout=0.2)
    finally:
        stop_event.set()
        if task.done():
            await task
        else:
            await asyncio.wait_for(task, timeout=0.2)

    return event, source.calls


def test_worker_retries_a_transient_source_failure_on_the_next_poll() -> None:
    event, source_calls = asyncio.run(receive_after_a_transient_source_failure())

    assert source_calls == 2
    positions = event["positions"]
    assert isinstance(positions, list)
    assert positions[0]["trip_id"] == "trip-42"


def test_snapshot_cycle_id_is_stable_for_identical_cycle_inputs() -> None:
    observed_at = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)

    first = _position_snapshot_cycle_id(
        feed_timestamp=1_784_457_500,
        observed_at=observed_at,
    )
    second = _position_snapshot_cycle_id(
        feed_timestamp=1_784_457_500,
        observed_at=observed_at,
    )

    assert first == second
