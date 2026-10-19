import asyncio
from dataclasses import replace
from datetime import date, datetime, timezone

from bvg_radar.realtime.benchmark import (
    CycleSample,
    JsonMeasurementPublisher,
    TimedPositionEventSerializer,
    TimedQueryConnection,
    TimedSource,
    TimedTripPositionEstimator,
    build_summary,
    measure_worker_cycle,
    validate_local_database_url,
)
from bvg_radar.realtime.contracts import EstimatedVehiclePosition
from bvg_radar.realtime.models import (
    GtfsRealtimeFetchResult,
    GtfsRealtimeFetchStatus,
    GtfsRealtimeSnapshot,
    TripUpdate,
)


def sample(total_cycle_seconds: float, sql_queries: int = 1) -> CycleSample:
    return CycleSample(
        trip_updates_received=10,
        matchable_trip_updates=8,
        positions_published=3,
        snapshots_published=1,
        sql_queries=sql_queries,
        download_and_normalization_seconds=0.2,
        database_and_adapter_seconds=0.5,
        contract_serialization_seconds=0.01,
        publication_json_seconds=0.01,
        orchestration_seconds=max(0.0, total_cycle_seconds - 0.72),
        total_cycle_seconds=total_cycle_seconds,
        payload_bytes=2048,
    )


def test_benchmark_summary_uses_fail_closed_nearest_rank_p95() -> None:
    samples = tuple(sample(value) for value in (1.0, 2.0, 3.0, 4.0, 5.0))

    passing = build_summary(samples, batch_size=256, target_cycle_seconds=5.1)
    failing = build_summary(samples, batch_size=256, target_cycle_seconds=5.0)
    excessive_queries = build_summary(
        (sample(1.0, sql_queries=2),),
        batch_size=256,
        target_cycle_seconds=5.0,
    )
    empty_feed = build_summary(
        (
            replace(
                sample(1.0, sql_queries=0),
                trip_updates_received=0,
                matchable_trip_updates=0,
                positions_published=0,
            ),
        ),
        batch_size=256,
        target_cycle_seconds=5.0,
    )

    assert passing["p95_total_cycle_seconds"] == 5.0
    assert passing["query_budget_passed"] is True
    assert passing["passed"] is True
    assert passing["max_sql_queries"] == 1
    assert len(passing["cycles"]) == 5
    assert failing["passed"] is False
    assert excessive_queries["query_budget_passed"] is False
    assert excessive_queries["passed"] is False
    assert empty_feed["feed_data_passed"] is False
    assert empty_feed["passed"] is False


def test_benchmark_summary_rejects_a_non_finite_target() -> None:
    try:
        build_summary(
            (sample(1.0),),
            batch_size=256,
            target_cycle_seconds=float("inf"),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("non-finite target was accepted")


def test_benchmark_accepts_only_the_project_local_database() -> None:
    assert (
        validate_local_database_url(
            "postgresql://postgres:test@127.0.0.1:55031/postgres"
        )
        == "postgresql://postgres:test@127.0.0.1:55031/postgres"
    )

    for unsafe_url in (
        "postgresql://postgres:test@example.com:55031/postgres",
        "postgresql://postgres:test@127.0.0.1:5432/postgres",
        "postgresql://postgres:test@127.0.0.1:55031/postgres?host=example.com",
        "https://127.0.0.1:55031/postgres",
    ):
        try:
            validate_local_database_url(unsafe_url)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe benchmark URL was accepted: {unsafe_url}")


class StepClock:
    def __init__(self, step: float = 0.125) -> None:
        self._value = -step
        self._step = step

    def __call__(self) -> float:
        self._value += self._step
        return self._value


class FakeSource:
    async def fetch(self) -> str:
        return "snapshot"


class FakeConnection:
    async def fetch(self, _query: str, *_arguments: object) -> tuple[str, ...]:
        return ("batch-row",)

    async def fetchrow(self, _query: str, *_arguments: object) -> str:
        return "single-row"


class SerializablePosition:
    def to_websocket_event(self) -> dict[str, object]:
        return {"type": "vehicle_position"}


async def exercise_boundary_instrumentation() -> None:
    source = TimedSource(FakeSource(), clock=StepClock())
    connection = TimedQueryConnection(FakeConnection(), clock=StepClock())
    serializer = TimedPositionEventSerializer(clock=StepClock())
    publisher = JsonMeasurementPublisher(clock=StepClock())

    assert await source.fetch() == "snapshot"
    assert await connection.fetch("batch", 1) == ("batch-row",)
    assert await connection.fetchrow("single", 2) == "single-row"
    event = serializer(SerializablePosition())
    await publisher.publish(event)

    assert source.elapsed_seconds == 0.125
    assert source.latest_result == "snapshot"
    assert connection.elapsed_seconds == 0.25
    assert connection.query_count == 2
    assert serializer.elapsed_seconds == 0.125
    assert serializer.position_count == 1
    assert publisher.elapsed_seconds == 0.125
    assert publisher.event_count == 1
    assert publisher.payload_bytes == len(b'{"type":"vehicle_position"}')


def test_benchmark_instrumentation_records_each_boundary() -> None:
    asyncio.run(exercise_boundary_instrumentation())


class BenchmarkSource:
    def __init__(self, *updates: TripUpdate) -> None:
        self._result = GtfsRealtimeFetchResult(
            status=GtfsRealtimeFetchStatus.UPDATED,
            snapshot=GtfsRealtimeSnapshot(
                feed_timestamp=1_784_457_500,
                trip_updates=updates,
            ),
        )

    async def fetch(self) -> GtfsRealtimeFetchResult:
        return self._result


class BenchmarkEstimator:
    def __init__(self, connection: TimedQueryConnection) -> None:
        self._connection = connection

    async def estimate_many(
        self,
        updates: tuple[TripUpdate, ...],
        observed_at: datetime,
        max_positions: int | None = None,
    ) -> tuple[EstimatedVehiclePosition, ...]:
        await self._connection.fetch("batch")
        return tuple(
            EstimatedVehiclePosition(
                entity_id=update.entity_id,
                trip_id=update.trip_id or "",
                route_id=update.route_id,
                shape_id=f"shape-{index}",
                previous_stop_id="stop-1",
                next_stop_id="stop-2",
                delay_seconds=30,
                estimated_next_arrival=observed_at,
                longitude=13.4,
                latitude=52.5,
                bearing_degrees=90.0,
                speed_mps=8.0,
                observed_at=observed_at,
                timing_source="realtime_delay",
                feed_timestamp=None,
                trip_update_timestamp=None,
                service_date=update.service_date,
                is_estimated=True,
                position_status="estimated_from_trip_update",
            )
            for index, update in enumerate(updates, start=1)
        )


async def exercise_complete_cycle_measurement() -> CycleSample:
    update = TripUpdate(
        entity_id="entity-1",
        trip_id="trip-1",
        route_id="route-1",
        service_date=date(2026, 7, 19),
        trip_update_timestamp=None,
        stop_time_updates=(),
    )
    source = TimedSource(BenchmarkSource(update), clock=StepClock(0.01))
    connection = TimedQueryConnection(FakeConnection(), clock=StepClock(0.01))
    estimator = TimedTripPositionEstimator(
        BenchmarkEstimator(connection),
        clock=StepClock(0.02),
    )
    serializer = TimedPositionEventSerializer(clock=StepClock(0.01))
    publisher = JsonMeasurementPublisher(clock=StepClock(0.01))

    return await measure_worker_cycle(
        source=source,
        estimator=estimator,
        connection=connection,
        serializer=serializer,
        publisher=publisher,
        observed_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc),
        clock=StepClock(1.0),
    )


def test_complete_cycle_measurement_builds_a_reproducible_sample() -> None:
    result = asyncio.run(exercise_complete_cycle_measurement())

    assert result.trip_updates_received == 1
    assert result.matchable_trip_updates == 1
    assert result.positions_published == 1
    assert result.snapshots_published == 1
    assert result.sql_queries == 1
    assert result.download_and_normalization_seconds == 0.01
    assert result.database_and_adapter_seconds == 0.02
    assert result.contract_serialization_seconds == 0.01
    assert result.publication_json_seconds == 0.01
    assert result.orchestration_seconds == 0.95
    assert result.total_cycle_seconds == 1.0
    assert result.payload_bytes > 0


async def exercise_two_position_snapshot_measurement() -> tuple[
    CycleSample,
    JsonMeasurementPublisher,
    TimedPositionEventSerializer,
]:
    first = TripUpdate(
        entity_id="entity-1",
        trip_id="trip-1",
        route_id="route-1",
        service_date=date(2026, 7, 19),
        trip_update_timestamp=None,
        stop_time_updates=(),
    )
    second = replace(first, entity_id="entity-2", trip_id="trip-2")
    source = TimedSource(BenchmarkSource(first, second), clock=StepClock(0.01))
    connection = TimedQueryConnection(FakeConnection(), clock=StepClock(0.01))
    estimator = TimedTripPositionEstimator(
        BenchmarkEstimator(connection),
        clock=StepClock(0.02),
    )
    serializer = TimedPositionEventSerializer(clock=StepClock(0.01))
    publisher = JsonMeasurementPublisher(clock=StepClock(0.01))

    result = await measure_worker_cycle(
        source=source,
        estimator=estimator,
        connection=connection,
        serializer=serializer,
        publisher=publisher,
        observed_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc),
        clock=StepClock(1.0),
    )
    return result, publisher, serializer


def test_cycle_measurement_counts_nested_positions_and_one_snapshot_independently() -> (
    None
):
    result, publisher, serializer = asyncio.run(
        exercise_two_position_snapshot_measurement()
    )

    assert result.positions_published == 2
    assert result.snapshots_published == 1
    assert serializer.position_count == 2
    assert publisher.event_count == 1
    assert result.payload_bytes == publisher.payload_bytes
    assert result.payload_bytes > 0
