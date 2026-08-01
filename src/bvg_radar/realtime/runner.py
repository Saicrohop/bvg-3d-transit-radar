"""One-cycle composition root for the server-side GTFS-Realtime ingestion engine.

This module deliberately writes JSON Lines to stdout for a dry-run. It does not
create an HTTP or WebSocket server; a future delivery adapter can replace the
publisher without changing the worker, source, or PostGIS estimator.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence, TextIO

import aiohttp
import asyncpg

from .gtfs_route_metadata import GtfsRouteMetadataLookup
from .source import AiohttpGtfsRealtimeSource
from .postgis import PostgisTripPositionEstimator
from .worker import (
    IngestionRunResult,
    PositionEventPublisher,
    TripUpdateIngestionWorker,
)

DEFAULT_VBB_GTFS_RT_URL = "https://production.gtfsrt.vbb.de/data"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class DryRunConfig:
    database_url: str
    feed_url: str = DEFAULT_VBB_GTFS_RT_URL
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    max_positions: int = 2

    def __post_init__(self) -> None:
        if not self.database_url:
            raise ValueError("database_url is required")
        if self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        if self.max_positions <= 0:
            raise ValueError("max_positions must be positive")


class JsonLinePositionEventPublisher:
    """Print future-WebSocket event payloads as one JSON object per line."""

    def __init__(self, output: TextIO) -> None:
        self._output = output

    async def publish(self, event: dict[str, object]) -> None:
        self._output.write(json.dumps(event, separators=(",", ":"), sort_keys=True) + "\n")
        self._output.flush()


def build_worker(
    session: aiohttp.ClientSession,
    connection: asyncpg.Pool,
    publisher: PositionEventPublisher,
    feed_url: str,
) -> TripUpdateIngestionWorker:
    """Wire outer infrastructure dependencies into the framework-independent worker."""
    return TripUpdateIngestionWorker(
        source=AiohttpGtfsRealtimeSource(session=session, url=feed_url),
        estimator=PostgisTripPositionEstimator(connection=connection),
        route_metadata_lookup=GtfsRouteMetadataLookup(connection),
        publisher=publisher,
    )


async def run_dry_run(
    config: DryRunConfig,
    publisher: PositionEventPublisher,
) -> IngestionRunResult:
    """Fetch one live feed, estimate up to ``max_positions``, then release resources."""
    timeout = aiohttp.ClientTimeout(total=config.request_timeout_seconds)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        pool = await asyncpg.create_pool(
            dsn=config.database_url,
            min_size=1,
            max_size=1,
            command_timeout=config.request_timeout_seconds,
        )
        try:
            worker = build_worker(
                session=session,
                connection=pool,
                publisher=publisher,
                feed_url=config.feed_url,
            )
            return await worker.run_once(
                observed_at=datetime.now(timezone.utc),
                max_positions=config.max_positions,
            )
        finally:
            await pool.close()


def parse_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one server-side VBB TripUpdate-to-position dry-run cycle."
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("BVG_DATABASE_URL"),
        help="PostgreSQL DSN, or set BVG_DATABASE_URL outside version control.",
    )
    parser.add_argument("--feed-url", default=DEFAULT_VBB_GTFS_RT_URL)
    parser.add_argument(
        "--request-timeout-seconds",
        default=DEFAULT_REQUEST_TIMEOUT_SECONDS,
        type=float,
    )
    parser.add_argument("--max-positions", default=2, type=int)
    return parser.parse_args(arguments)


async def _main(arguments: argparse.Namespace) -> int:
    config = DryRunConfig(
        database_url=arguments.database_url or "",
        feed_url=arguments.feed_url,
        request_timeout_seconds=arguments.request_timeout_seconds,
        max_positions=arguments.max_positions,
    )
    result = await run_dry_run(
        config=config,
        publisher=JsonLinePositionEventPublisher(sys.stdout),
    )
    print(
        json.dumps(
            {
                "type": "ingestion_cycle",
                "trip_updates_received": result.trip_updates_received,
                "estimated_positions_published": result.estimated_positions_published,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0 if result.estimated_positions_published else 2


def main(arguments: Sequence[str] | None = None) -> int:
    return asyncio.run(_main(parse_arguments(arguments)))


if __name__ == "__main__":
    raise SystemExit(main())
