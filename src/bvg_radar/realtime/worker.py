import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from .contracts import EstimatedVehiclePosition
from .models import TripUpdate
from .vehicle_category import classify_berlin_vehicle


class TripUpdateSource(Protocol):
    async def fetch_trip_updates(self) -> tuple[TripUpdate, ...]: ...


class TripPositionEstimator(Protocol):
    async def estimate(
        self, update: TripUpdate, observed_at: datetime
    ) -> EstimatedVehiclePosition | None: ...


class RouteMetadataRecord(Protocol):
    route_type: int
    route_short_name: str | None


class RouteMetadataLookup(Protocol):
    async def find_by_trip_id(self, trip_id: str) -> RouteMetadataRecord | None: ...


class PositionEventPublisher(Protocol):
    async def publish(self, event: dict[str, object]) -> None: ...


ErrorReporter = Callable[[Exception], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class IngestionRunResult:
    trip_updates_received: int
    estimated_positions_published: int


class AsyncQueuePositionEventPublisher:
    """In-memory output port that a future WebSocket adapter can consume."""

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
        route_metadata_lookup: RouteMetadataLookup,
        publisher: PositionEventPublisher,
    ) -> None:
        self._source = source
        self._estimator = estimator
        self._route_metadata_lookup = route_metadata_lookup
        self._publisher = publisher

    async def run_once(
        self,
        observed_at: datetime,
        max_positions: int | None = None,
    ) -> IngestionRunResult:
        if max_positions is not None and max_positions <= 0:
            raise ValueError("max_positions must be positive when provided")

        updates = await self._source.fetch_trip_updates()
        published = 0
        for update in updates:
            estimate = await self._estimator.estimate(update, observed_at)
            if estimate is None:
                continue
            metadata = await self._route_metadata_lookup.find_by_trip_id(
                estimate.trip_id
            )
            category = (
                None
                if metadata is None
                else classify_berlin_vehicle(
                    metadata.route_type,
                    metadata.route_short_name,
                )
            )
            estimate = replace(estimate, vehicle_category=category)
            await self._publisher.publish(estimate.to_websocket_event())
            published += 1
            if max_positions is not None and published >= max_positions:
                break
        return IngestionRunResult(
            trip_updates_received=len(updates),
            estimated_positions_published=published,
        )

    async def run_forever(
        self,
        interval_seconds: float,
        stop_event: asyncio.Event,
        now: Callable[[], datetime],
        on_error: ErrorReporter | None = None,
    ) -> None:
        """Poll on a monotonic cadence without blocking unrelated async tasks."""
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")

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
