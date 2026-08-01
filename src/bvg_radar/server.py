"""FastAPI composition root for local estimated-position WebSocket delivery."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timezone

import aiohttp
import asyncpg
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .realtime.gtfs_route_metadata import GtfsRouteMetadataLookup
from .realtime.postgis import PostgisTripPositionEstimator
from .realtime.source import AiohttpGtfsRealtimeSource
from .realtime.websocket import PositionWebSocketHub
from .realtime.worker import TripUpdateIngestionWorker

DEFAULT_VBB_GTFS_RT_URL = "https://production.gtfsrt.vbb.de/data"
logger = logging.getLogger(__name__)
AppLifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


@dataclass(frozen=True, slots=True)
class RealtimeServerSettings:
    database_url: str
    feed_url: str = DEFAULT_VBB_GTFS_RT_URL
    poll_interval_seconds: float = 15.0
    request_timeout_seconds: float = 30.0
    database_pool_size: int = 8

    def __post_init__(self) -> None:
        if not self.database_url:
            raise ValueError("database_url is required")
        if self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        if self.database_pool_size <= 0:
            raise ValueError("database_pool_size must be positive")

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> "RealtimeServerSettings":
        values = os.environ if environment is None else environment
        return cls(
            database_url=values.get("BVG_DATABASE_URL", ""),
            feed_url=values.get("BVG_GTFS_RT_URL", DEFAULT_VBB_GTFS_RT_URL),
            poll_interval_seconds=float(values.get("BVG_WS_POLL_INTERVAL_SECONDS", "15")),
            request_timeout_seconds=float(
                values.get("BVG_WS_REQUEST_TIMEOUT_SECONDS", "30")
            ),
            database_pool_size=int(values.get("BVG_WS_DB_POOL_SIZE", "8")),
        )


def create_transport_app(
    position_hub: PositionWebSocketHub,
    lifespan: AppLifespan | None = None,
) -> FastAPI:
    """Expose normalized events without relaying GTFS-Realtime Protobuf."""
    app = FastAPI(title="BVG 3D Transit Radar", lifespan=lifespan)
    app.state.position_hub = position_hub

    @app.websocket("/ws/positions")
    async def positions(websocket: WebSocket) -> None:
        await position_hub.connect(websocket)
        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
        except WebSocketDisconnect:
            pass
        finally:
            await position_hub.disconnect(websocket)

    return app


def create_app(settings: RealtimeServerSettings | None = None) -> FastAPI:
    """Create the local WebSocket server and start ingestion only in lifespan."""
    effective_settings = settings or RealtimeServerSettings.from_environment()
    position_hub = PositionWebSocketHub()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        timeout = aiohttp.ClientTimeout(total=effective_settings.request_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            pool = await asyncpg.create_pool(
                dsn=effective_settings.database_url,
                min_size=1,
                max_size=effective_settings.database_pool_size,
                command_timeout=effective_settings.request_timeout_seconds,
            )
            stop_event = asyncio.Event()
            worker = TripUpdateIngestionWorker(
                source=AiohttpGtfsRealtimeSource(session, effective_settings.feed_url),
                estimator=PostgisTripPositionEstimator(pool),
                route_metadata_lookup=GtfsRouteMetadataLookup(pool),
                publisher=position_hub,
            )
            task = asyncio.create_task(
                worker.run_forever(
                    interval_seconds=effective_settings.poll_interval_seconds,
                    stop_event=stop_event,
                    now=lambda: datetime.now(timezone.utc),
                    on_error=_log_ingestion_error,
                ),
                name="vbb-trip-update-ingestion",
            )
            app.state.ingestion_task = task
            try:
                yield
            finally:
                stop_event.set()
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
                await pool.close()

    return create_transport_app(position_hub, lifespan=lifespan)


async def _log_ingestion_error(error: Exception) -> None:
    logger.warning("VBB TripUpdate ingestion cycle failed; retrying on next poll: %s", error)
