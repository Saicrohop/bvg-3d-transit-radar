import asyncio
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


class FailsOnceSource(StaticSource):
    def __init__(self, updates: tuple[TripUpdate, ...]) -> None:
        super().__init__(updates)
        self.calls = 0

    async def fetch(self) -> GtfsRealtimeFetchResult:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient VBB failure")
        return await super().fetch()


class MissingRouteMetadataLookup:
    async def find_by_trip_id(self, _trip_id: str) -> None:
        return None


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
        )


class CountingEstimator(MatchingEstimator):
    def __init__(self) -> None:
        self.calls = 0

    async def estimate(
        self, update: TripUpdate, observed_at: datetime
    ) -> EstimatedVehiclePosition | None:
        self.calls += 1
        return await super().estimate(update, observed_at)


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
        route_metadata_lookup=MissingRouteMetadataLookup(),
        publisher=AsyncQueuePositionEventPublisher(queue),
    )

    result = asyncio.run(
        worker.run_once(
            observed_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)
        )
    )

    assert result.trip_updates_received == 1
    assert result.estimated_positions_published == 0
    assert estimator.calls == 0
    assert queue.empty()


def test_worker_preserves_feed_timestamp_and_deleted_entity_ids() -> None:
    worker = TripUpdateIngestionWorker(
        source=StaticSource(
            updates=(),
            deleted_entities=(DeletedFeedEntity("entity-removed"),),
        ),
        estimator=CountingEstimator(),
        route_metadata_lookup=MissingRouteMetadataLookup(),
        publisher=AsyncQueuePositionEventPublisher(asyncio.Queue()),
    )

    result = asyncio.run(
        worker.run_once(
            observed_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)
        )
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
        route_metadata_lookup=MissingRouteMetadataLookup(),
        publisher=AsyncQueuePositionEventPublisher(asyncio.Queue()),
    )

    result = asyncio.run(
        worker.run_once(
            observed_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)
        )
    )

    assert result.trip_updates_received == 1
    assert result.estimated_positions_published == 0
    assert estimator.calls == 0


def test_worker_publishes_estimated_vehicle_position_contract() -> None:
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    worker = TripUpdateIngestionWorker(
        source=StaticSource((trip_update("trip-42"), trip_update("trip-without-segment"))),
        estimator=MatchingEstimator(),
        route_metadata_lookup=MissingRouteMetadataLookup(),
        publisher=AsyncQueuePositionEventPublisher(queue),
    )
    observed_at = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)

    result = asyncio.run(worker.run_once(observed_at=observed_at))

    assert result.trip_updates_received == 2
    assert result.estimated_positions_published == 1
    event = queue.get_nowait()
    assert event == {
        "type": "vehicle_position",
        "source": "trip_update_interpolation",
        "is_estimated": True,
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


def test_worker_stops_scanning_after_the_requested_position_limit() -> None:
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    estimator = CountingEstimator()
    worker = TripUpdateIngestionWorker(
        source=StaticSource((trip_update("trip-42"), trip_update("trip-42"))),
        estimator=estimator,
        route_metadata_lookup=MissingRouteMetadataLookup(),
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
        route_metadata_lookup=MissingRouteMetadataLookup(),
        publisher=RecordingPublisher(operations),
    )

    result = asyncio.run(
        worker.run_once(
            observed_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)
        )
    )

    assert result.estimated_positions_published == 2
    assert operations == ["estimate", "estimate", "publish", "publish"]


async def receive_after_a_transient_source_failure() -> tuple[dict[str, object], int]:
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    source = FailsOnceSource((trip_update("trip-42"),))
    worker = TripUpdateIngestionWorker(
        source=source,
        estimator=MatchingEstimator(),
        route_metadata_lookup=MissingRouteMetadataLookup(),
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
    assert event["trip_id"] == "trip-42"
