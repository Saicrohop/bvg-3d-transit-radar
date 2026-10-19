import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from .analytics import RouteAnalyticsRecorder, aggregate_route_observations
from .contracts import EstimatedVehiclePosition, VehiclePositionSnapshot
from .models import (
    GtfsRealtimeFetchResult,
    GtfsRealtimeFetchStatus,
    TripUpdate,
)
from .normalization import (
    InvalidGtfsRealtimeRecord,
    InvalidGtfsRealtimeTimestamp,
    timestamp_as_utc,
    validate_snapshot_timestamps,
)
from .source import GtfsRealtimeFetchError


DEFAULT_ROUTE_ANALYTICS_TIMEOUT_SECONDS = 1.0
logger = logging.getLogger(__name__)


class InvalidIngestionCycleError(ValueError):
    """A deterministic input or snapshot contract failure, not a port outage."""


def _validate_observed_at(observed_at: datetime) -> None:
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
        raise InvalidIngestionCycleError("observed_at must be timezone-aware")
    try:
        if observed_at.utcoffset() is None:
            raise ValueError("missing UTC offset")
        observed_at.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise InvalidIngestionCycleError(
            "observed_at must be representable in UTC"
        ) from error


class TripUpdateSource(Protocol):
    async def fetch(self) -> GtfsRealtimeFetchResult: ...


class TripPositionEstimator(Protocol):
    async def estimate_many(
        self,
        updates: tuple[TripUpdate, ...],
        observed_at: datetime,
        max_positions: int | None = None,
    ) -> tuple[EstimatedVehiclePosition, ...]: ...


class PositionEventPublisher(Protocol):
    async def publish(self, event: dict[str, object]) -> None: ...


ErrorReporter = Callable[[Exception], Awaitable[None]]
PositionEventSerializer = Callable[
    [EstimatedVehiclePosition],
    dict[str, object],
]


def serialize_position_event(
    position: EstimatedVehiclePosition,
) -> dict[str, object]:
    try:
        return position.to_websocket_event()
    except (ValueError, OverflowError) as error:
        raise InvalidIngestionCycleError("invalid vehicle position contract") from error


def _position_snapshot_cycle_id(
    feed_timestamp: int | None,
    observed_at: datetime,
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"bvg-position-snapshot:{feed_timestamp}:{observed_at.isoformat()}",
        )
    )


@dataclass(frozen=True, slots=True)
class IngestionRunResult:
    trip_updates_received: int
    estimated_positions_published: int
    position_snapshots_published: int
    fetch_status: GtfsRealtimeFetchStatus
    feed_timestamp: int | None
    deleted_entity_ids: tuple[str, ...]


class AsyncQueuePositionEventPublisher:
    """In-memory output port for complete WebSocket snapshot events."""

    def __init__(self, queue: asyncio.Queue[dict[str, object]]) -> None:
        self._queue = queue

    async def publish(self, event: dict[str, object]) -> None:
        await self._queue.put(event)


class TripUpdateIngestionWorker:
    """Coordinates source, estimator and output without depending on FastAPI."""

    def __init__(
        self,
        source: TripUpdateSource,
        estimator: TripPositionEstimator,
        publisher: PositionEventPublisher,
        serialize_position: PositionEventSerializer = serialize_position_event,
        analytics_recorder: RouteAnalyticsRecorder | None = None,
        analytics_timeout_seconds: float = DEFAULT_ROUTE_ANALYTICS_TIMEOUT_SECONDS,
    ) -> None:
        self._source = source
        self._estimator = estimator
        self._publisher = publisher
        self._serialize_position = serialize_position
        self._analytics_recorder = analytics_recorder
        if (
            type(analytics_timeout_seconds) not in (int, float)
            or not math.isfinite(analytics_timeout_seconds)
            or analytics_timeout_seconds <= 0
        ):
            raise ValueError("analytics_timeout_seconds must be finite and positive")
        self._analytics_timeout_seconds = analytics_timeout_seconds
        # One unacknowledged cycle only: no polling ahead, no synthetic refresh.
        self._pending_cycle: (
            tuple[GtfsRealtimeFetchResult, datetime, int | None] | None
        ) = None

    async def run_once(
        self,
        observed_at: datetime,
        max_positions: int | None = None,
    ) -> IngestionRunResult:
        if max_positions is not None and (
            type(max_positions) is not int or max_positions <= 0
        ):
            raise ValueError("max_positions must be positive when provided")

        if self._pending_cycle is None:
            _validate_observed_at(observed_at)
            fetch_result = await self._source.fetch()
            if fetch_result.snapshot is not None:
                try:
                    validate_snapshot_timestamps(fetch_result.snapshot)
                except (
                    InvalidGtfsRealtimeRecord,
                    InvalidGtfsRealtimeTimestamp,
                ) as error:
                    raise GtfsRealtimeFetchError(
                        "GTFS-RT snapshot contains an invalid timestamp or stop value"
                    ) from error
                self._pending_cycle = (fetch_result, observed_at, max_positions)
        else:
            fetch_result, observed_at, max_positions = self._pending_cycle
        snapshot = fetch_result.snapshot
        if snapshot is None:
            return IngestionRunResult(
                trip_updates_received=0,
                estimated_positions_published=0,
                position_snapshots_published=0,
                fetch_status=fetch_result.status,
                feed_timestamp=None,
                deleted_entity_ids=(),
            )

        updates = snapshot.trip_updates
        feed_timestamp = timestamp_as_utc(snapshot.feed_timestamp)
        matchable_updates = tuple(
            update for update in updates if update.is_static_schedule_matchable
        )
        estimates = (
            ()
            if not matchable_updates
            else await self._estimator.estimate_many(
                matchable_updates,
                observed_at,
                max_positions=max_positions,
            )
        )
        # Application-owned construction checks are deterministic contract failures.
        try:
            positions_by_trip = {
                estimate.trip_id: replace(estimate, feed_timestamp=feed_timestamp)
                for estimate in estimates
            }
            positions = tuple(positions_by_trip.values())
            position_snapshot = VehiclePositionSnapshot(
                cycle_id=_position_snapshot_cycle_id(
                    snapshot.feed_timestamp,
                    observed_at,
                ),
                feed_timestamp=feed_timestamp,
                observed_at=observed_at,
                positions=positions,
                trip_updates_received=len(updates),
                positions_suppressed=len(updates) - len(positions),
            )
        except (ValueError, OverflowError) as error:
            self._pending_cycle = None
            raise InvalidIngestionCycleError(
                "invalid vehicle position snapshot contract"
            ) from error

        # Extension ports may fail transiently, even with ValueError. Only the
        # built-in serializer's typed contract rejection discards the cycle.
        try:
            event = position_snapshot.to_websocket_event(self._serialize_position)
        except InvalidIngestionCycleError:
            self._pending_cycle = None
            raise
        await self._publisher.publish(event)
        await self._record_route_analytics(position_snapshot, positions)
        self._pending_cycle = None

        return IngestionRunResult(
            trip_updates_received=len(updates),
            estimated_positions_published=len(positions),
            position_snapshots_published=1,
            fetch_status=fetch_result.status,
            feed_timestamp=snapshot.feed_timestamp,
            deleted_entity_ids=tuple(
                entity.entity_id for entity in snapshot.deleted_entities
            ),
        )

    async def _record_route_analytics(
        self,
        position_snapshot: VehiclePositionSnapshot,
        positions: tuple[EstimatedVehiclePosition, ...],
    ) -> None:
        if self._analytics_recorder is None:
            return
        rows = aggregate_route_observations(positions)
        if not rows:
            return
        try:
            async with asyncio.timeout(self._analytics_timeout_seconds):
                await self._analytics_recorder.record_cycle(
                    position_snapshot.cycle_id,
                    position_snapshot.observed_at,
                    rows,
                )
        except Exception as error:
            logger.warning(
                "route punctuality analytics write failed; cycle_id=%s error_type=%s",
                position_snapshot.cycle_id,
                type(error).__name__,
            )

    async def run_forever(
        self,
        interval_seconds: float,
        stop_event: asyncio.Event,
        now: Callable[[], datetime],
        on_error: ErrorReporter | None = None,
    ) -> None:
        """Poll on a monotonic cadence without blocking unrelated async tasks."""
        if (
            type(interval_seconds) not in (int, float)
            or not math.isfinite(interval_seconds)
            or interval_seconds <= 0
        ):
            raise ValueError("interval_seconds must be finite and positive")

        loop = asyncio.get_running_loop()
        next_run = loop.time()
        while not stop_event.is_set():
            try:
                await self.run_once(now())
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if on_error is not None:
                    await on_error(error)
            next_run += interval_seconds
            delay = max(0.0, next_run - loop.time())
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=delay)
            except TimeoutError:
                pass
