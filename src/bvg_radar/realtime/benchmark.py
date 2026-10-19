from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from time import perf_counter
from typing import Protocol
from urllib.parse import urlparse

from .contracts import EstimatedVehiclePosition
from .models import GtfsRealtimeFetchResult, TripUpdate
from .worker import IngestionRunResult, TripPositionEstimator, TripUpdateIngestionWorker

LOCAL_DATABASE_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
LOCAL_DATABASE_PORT = 55031


class _FetchSource(Protocol):
    async def fetch(self) -> object: ...


class _QueryConnection(Protocol):
    async def fetch(self, query: str, *arguments: object) -> Sequence[object]: ...

    async def fetchrow(self, query: str, *arguments: object) -> object | None: ...


class TimedSource:
    def __init__(
        self,
        source: _FetchSource,
        *,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        self._source = source
        self._clock = clock
        self.elapsed_seconds = 0.0
        self.latest_result: object | None = None

    async def fetch(self) -> object:
        started_at = self._clock()
        try:
            result = await self._source.fetch()
            self.latest_result = result
            return result
        finally:
            self.elapsed_seconds += self._clock() - started_at


class TimedQueryConnection:
    def __init__(
        self,
        connection: _QueryConnection,
        *,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        self._connection = connection
        self._clock = clock
        self.elapsed_seconds = 0.0
        self.query_count = 0

    async def fetch(self, query: str, *arguments: object) -> Sequence[object]:
        started_at = self._clock()
        self.query_count += 1
        try:
            return await self._connection.fetch(query, *arguments)
        finally:
            self.elapsed_seconds += self._clock() - started_at

    async def fetchrow(self, query: str, *arguments: object) -> object | None:
        started_at = self._clock()
        self.query_count += 1
        try:
            return await self._connection.fetchrow(query, *arguments)
        finally:
            self.elapsed_seconds += self._clock() - started_at


class TimedTripPositionEstimator:
    def __init__(
        self,
        estimator: TripPositionEstimator,
        *,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        self._estimator = estimator
        self._clock = clock
        self.elapsed_seconds = 0.0

    async def estimate_many(
        self,
        updates: tuple[TripUpdate, ...],
        observed_at: datetime,
        max_positions: int | None = None,
    ) -> tuple[EstimatedVehiclePosition, ...]:
        started_at = self._clock()
        try:
            return await self._estimator.estimate_many(
                updates,
                observed_at,
                max_positions=max_positions,
            )
        finally:
            self.elapsed_seconds += self._clock() - started_at


class TimedPositionEventSerializer:
    def __init__(self, *, clock: Callable[[], float] = perf_counter) -> None:
        self._clock = clock
        self.elapsed_seconds = 0.0
        self.position_count = 0

    def __call__(
        self,
        position: EstimatedVehiclePosition,
    ) -> dict[str, object]:
        started_at = self._clock()
        try:
            event = position.to_websocket_event()
            self.position_count += 1
            return event
        finally:
            self.elapsed_seconds += self._clock() - started_at


class JsonMeasurementPublisher:
    def __init__(self, *, clock: Callable[[], float] = perf_counter) -> None:
        self._clock = clock
        self.elapsed_seconds = 0.0
        self.event_count = 0
        self.payload_bytes = 0

    async def publish(self, event: dict[str, object]) -> None:
        started_at = self._clock()
        try:
            payload = json.dumps(
                event,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            self.event_count += 1
            self.payload_bytes += len(payload)
        finally:
            self.elapsed_seconds += self._clock() - started_at


@dataclass(frozen=True, slots=True)
class CycleSample:
    trip_updates_received: int
    matchable_trip_updates: int
    positions_published: int
    snapshots_published: int
    sql_queries: int
    download_and_normalization_seconds: float
    database_and_adapter_seconds: float
    contract_serialization_seconds: float
    publication_json_seconds: float
    orchestration_seconds: float
    total_cycle_seconds: float
    payload_bytes: int


async def measure_worker_cycle(
    *,
    source: TimedSource,
    estimator: TimedTripPositionEstimator,
    connection: TimedQueryConnection,
    serializer: TimedPositionEventSerializer,
    publisher: JsonMeasurementPublisher,
    observed_at: datetime,
    clock: Callable[[], float] = perf_counter,
) -> CycleSample:
    worker = TripUpdateIngestionWorker(
        source=source,
        estimator=estimator,
        publisher=publisher,
        serialize_position=serializer,
    )
    started_at = clock()
    result: IngestionRunResult = await worker.run_once(observed_at)
    total_cycle_seconds = clock() - started_at

    fetch_result = source.latest_result
    if not isinstance(fetch_result, GtfsRealtimeFetchResult):
        raise RuntimeError("benchmark source did not retain a GTFS-Realtime result")
    snapshot = fetch_result.snapshot
    matchable_trip_updates = (
        0
        if snapshot is None
        else sum(
            update.is_static_schedule_matchable for update in snapshot.trip_updates
        )
    )
    expected_snapshot_count = 0 if snapshot is None else 1
    if (
        result.position_snapshots_published != expected_snapshot_count
        or serializer.position_count != result.estimated_positions_published
        or publisher.event_count != result.position_snapshots_published
    ):
        raise RuntimeError("benchmark instrumentation lost positions or snapshots")

    measured_seconds = (
        source.elapsed_seconds
        + estimator.elapsed_seconds
        + serializer.elapsed_seconds
        + publisher.elapsed_seconds
    )
    return CycleSample(
        trip_updates_received=result.trip_updates_received,
        matchable_trip_updates=matchable_trip_updates,
        positions_published=result.estimated_positions_published,
        snapshots_published=result.position_snapshots_published,
        sql_queries=connection.query_count,
        download_and_normalization_seconds=round(source.elapsed_seconds, 6),
        database_and_adapter_seconds=round(estimator.elapsed_seconds, 6),
        contract_serialization_seconds=round(serializer.elapsed_seconds, 6),
        publication_json_seconds=round(publisher.elapsed_seconds, 6),
        orchestration_seconds=round(
            max(0.0, total_cycle_seconds - measured_seconds),
            6,
        ),
        total_cycle_seconds=round(total_cycle_seconds, 6),
        payload_bytes=publisher.payload_bytes,
    )


def validate_local_database_url(database_url: str) -> str:
    message = (
        f"database must be PostgreSQL on project-local loopback port {LOCAL_DATABASE_PORT} "
        "without URL overrides"
    )
    if not isinstance(database_url, str):
        raise ValueError(message)
    try:
        parsed = urlparse(database_url)
        allowed = (
            parsed.scheme in {"postgres", "postgresql"}
            and parsed.hostname in LOCAL_DATABASE_HOSTS
            and parsed.port == LOCAL_DATABASE_PORT
            and not parsed.params
            and ';' not in parsed.path
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        # urllib errors can echo arbitrary input, including the supplied port.
        raise ValueError(message) from None
    if not allowed:
        raise ValueError(message)
    return database_url


def _nearest_rank_percentile(values: tuple[float, ...], percentile: float) -> float:
    if not values:
        raise ValueError("at least one benchmark sample is required")
    rank = max(1, math.ceil(percentile * len(values)))
    return sorted(values)[rank - 1]


def _validate_sample(sample: CycleSample) -> None:
    for field in (
        "trip_updates_received",
        "matchable_trip_updates",
        "positions_published",
        "snapshots_published",
        "sql_queries",
        "payload_bytes",
    ):
        value = getattr(sample, field)
        if type(value) is not int or value < 0:
            raise ValueError(f"benchmark sample {field} must be a nonnegative integer")
    for field in (
        "download_and_normalization_seconds",
        "database_and_adapter_seconds",
        "contract_serialization_seconds",
        "publication_json_seconds",
        "orchestration_seconds",
        "total_cycle_seconds",
    ):
        value = getattr(sample, field)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f"benchmark sample {field} must be finite and nonnegative")
    if (
        sample.matchable_trip_updates > sample.trip_updates_received
        or sample.positions_published > sample.matchable_trip_updates
        or sample.snapshots_published not in (0, 1)
        or (sample.positions_published > 0 and sample.snapshots_published != 1)
    ):
        raise ValueError("benchmark sample counts are inconsistent")


def build_summary(
    samples: tuple[CycleSample, ...],
    *,
    batch_size: int,
    target_cycle_seconds: float,
) -> dict[str, object]:
    if type(batch_size) is not int or batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if not math.isfinite(target_cycle_seconds) or target_cycle_seconds <= 0:
        raise ValueError("target_cycle_seconds must be finite and positive")

    for sample in samples:
        _validate_sample(sample)

    p95 = _nearest_rank_percentile(
        tuple(sample.total_cycle_seconds for sample in samples), 0.95
    )
    query_budget_passed = all(
        sample.sql_queries == math.ceil(sample.matchable_trip_updates / batch_size)
        for sample in samples
    )
    # Empty UPDATED and NOT_MODIFIED cycles are legitimate. Evidence is required
    # across the sample, not fabricated for each individual cycle.
    feed_data_passed = any(
        sample.trip_updates_received > 0 and sample.matchable_trip_updates > 0
        for sample in samples
    )
    performance_passed = p95 < target_cycle_seconds and query_budget_passed
    data_gate_passed = feed_data_passed and any(
        sample.positions_published > 0 for sample in samples
    )
    return {
        "schema_version": 1,
        "batch_size": batch_size,
        "iterations": len(samples),
        "target_cycle_seconds": target_cycle_seconds,
        "p95_total_cycle_seconds": p95,
        "percentile_method": "nearest_rank",
        "p95_sample_count": len(samples),
        # Below 20 cycles the nearest-rank p95 is the maximum, not a tail study.
        "p95_small_sample": len(samples) < 20,
        "p95_is_sustained_load_evidence": False,
        "max_sql_queries": max(sample.sql_queries for sample in samples),
        "feed_data_passed": feed_data_passed,
        "query_budget_passed": query_budget_passed,
        "performance_passed": performance_passed,
        "data_gate_passed": data_gate_passed,
        "passed": performance_passed and data_gate_passed,
        "cycles": [asdict(sample) for sample in samples],
    }
