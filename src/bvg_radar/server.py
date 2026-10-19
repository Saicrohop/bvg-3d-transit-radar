"""FastAPI composition root for local estimated-position WebSocket delivery."""

from __future__ import annotations

import asyncio
import logging
import math
import os
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime

import aiohttp
import asyncpg
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router as analytics_api_router
from .realtime.analytics import AsyncpgRouteAnalyticsRecorder
from .realtime.postgis import PostgisTripPositionEstimator
from .realtime.source import AiohttpGtfsRealtimeSource
from .realtime.websocket import PositionWebSocketHub, SnapshotReplayError
from .realtime.worker import TripUpdateIngestionWorker

DEFAULT_VBB_GTFS_RT_URL = "https://production.gtfsrt.vbb.de/data"
LOCAL_API_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5175",
    "http://127.0.0.1:5175",
)
logger = logging.getLogger(__name__)
AppLifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


@dataclass(frozen=True, slots=True)
class RealtimeServerSettings:
    database_url: str
    feed_url: str = DEFAULT_VBB_GTFS_RT_URL
    poll_interval_seconds: float = 15.0
    request_timeout_seconds: float = 30.0
    send_timeout_seconds: float = 1.0
    database_pool_size: int = 8

    def __post_init__(self) -> None:
        if not self.database_url:
            raise ValueError("database_url is required")
        if (
            type(self.poll_interval_seconds) not in (int, float)
            or not math.isfinite(self.poll_interval_seconds)
            or self.poll_interval_seconds <= 0
        ):
            raise ValueError("poll_interval_seconds must be finite and positive")
        if (
            type(self.request_timeout_seconds) not in (int, float)
            or not math.isfinite(self.request_timeout_seconds)
            or self.request_timeout_seconds <= 0
        ):
            raise ValueError("request_timeout_seconds must be finite and positive")
        if (
            type(self.send_timeout_seconds) not in (int, float)
            or not math.isfinite(self.send_timeout_seconds)
            or self.send_timeout_seconds <= 0
        ):
            raise ValueError("send_timeout_seconds must be finite and positive")
        if type(self.database_pool_size) is not int or self.database_pool_size <= 0:
            raise ValueError("database_pool_size must be positive")

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> RealtimeServerSettings:
        values = os.environ if environment is None else environment
        return cls(
            database_url=values.get("BVG_DATABASE_URL", ""),
            feed_url=values.get("BVG_GTFS_RT_URL", DEFAULT_VBB_GTFS_RT_URL),
            poll_interval_seconds=float(
                values.get("BVG_WS_POLL_INTERVAL_SECONDS", "15")
            ),
            request_timeout_seconds=float(
                values.get("BVG_WS_REQUEST_TIMEOUT_SECONDS", "30")
            ),
            send_timeout_seconds=float(values.get("BVG_WS_SEND_TIMEOUT_SECONDS", "1")),
            database_pool_size=int(values.get("BVG_WS_DB_POOL_SIZE", "8")),
        )


async def _receive_until_disconnect(websocket: WebSocket) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return


async def _serve_position_websocket(
    websocket: WebSocket,
    position_hub: PositionWebSocketHub,
) -> None:
    try:
        await position_hub.connect(websocket)
    except (SnapshotReplayError, WebSocketDisconnect) as error:
        logger.debug("WebSocket connection/replay failed: %s", error)
        with suppress(RuntimeError):
            await websocket.close(code=1011)
        return

    receive_task = asyncio.create_task(_receive_until_disconnect(websocket))
    eviction_task = asyncio.create_task(position_hub.wait_until_disconnected(websocket))
    try:
        done, _pending = await asyncio.wait(
            (receive_task, eviction_task),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if eviction_task in done:
            receive_task.cancel()
            with suppress(asyncio.CancelledError, WebSocketDisconnect):
                await receive_task
            with suppress(RuntimeError):
                await websocket.close(code=1011)
        else:
            with suppress(WebSocketDisconnect):
                await receive_task
    finally:
        for task in (receive_task, eviction_task):
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        await position_hub.disconnect(websocket)


def create_transport_app(
    position_hub: PositionWebSocketHub,
    lifespan: AppLifespan | None = None,
) -> FastAPI:
    """Expose normalized events without relaying GTFS-Realtime Protobuf."""
    app = FastAPI(title="BVG 3D Transit Radar", lifespan=lifespan)
    app.state.position_hub = position_hub

    @app.websocket("/ws/positions")
    async def positions(websocket: WebSocket) -> None:
        await _serve_position_websocket(websocket, position_hub)

    return app


def create_app(settings: RealtimeServerSettings | None = None) -> FastAPI:
    """Create the local WebSocket server and start ingestion only in lifespan."""
    effective_settings = settings or RealtimeServerSettings.from_environment()
    position_hub = PositionWebSocketHub(
        send_timeout_seconds=effective_settings.send_timeout_seconds
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        timeout = aiohttp.ClientTimeout(
            total=effective_settings.request_timeout_seconds
        )
        async with aiohttp.ClientSession(timeout=timeout) as session:
            pool = await asyncpg.create_pool(
                dsn=effective_settings.database_url,
                min_size=1,
                max_size=effective_settings.database_pool_size,
                command_timeout=effective_settings.request_timeout_seconds,
            )
            app.state.database_pool = pool
            stop_event = asyncio.Event()
            worker = TripUpdateIngestionWorker(
                source=AiohttpGtfsRealtimeSource(session, effective_settings.feed_url),
                estimator=PostgisTripPositionEstimator(pool),
                publisher=position_hub,
                analytics_recorder=AsyncpgRouteAnalyticsRecorder(pool),
            )
            task = asyncio.create_task(
                worker.run_forever(
                    interval_seconds=effective_settings.poll_interval_seconds,
                    stop_event=stop_event,
                    now=lambda: datetime.now(UTC),
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
                app.state.database_pool = None

    app = create_transport_app(position_hub, lifespan=lifespan)
    app.include_router(analytics_api_router)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(LOCAL_API_CORS_ORIGINS),
        allow_methods=["GET"],
        allow_headers=["Accept", "Content-Type"],
    )
    app.state.database_pool = None
    return app


async def _log_ingestion_error(error: Exception) -> None:
    logger.warning(
        "VBB TripUpdate ingestion cycle failed; retrying on next poll: %s", error
    )
