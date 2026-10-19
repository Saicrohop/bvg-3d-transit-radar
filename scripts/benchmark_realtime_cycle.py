from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
from datetime import UTC, datetime

import aiohttp
import asyncpg

from bvg_radar.realtime.benchmark import (
    JsonMeasurementPublisher,
    TimedPositionEventSerializer,
    TimedQueryConnection,
    TimedSource,
    TimedTripPositionEstimator,
    build_summary,
    measure_worker_cycle,
    validate_local_database_url,
)
from bvg_radar.realtime.postgis import (
    DEFAULT_BATCH_SIZE,
    PostgisTripPositionEstimator,
)
from bvg_radar.realtime.source import AiohttpGtfsRealtimeSource

DEFAULT_FEED_URL = "https://production.gtfsrt.vbb.de/data"
DEFAULT_ITERATIONS = 5
DEFAULT_TARGET_CYCLE_SECONDS = 15.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Measure complete VBB TripUpdate-to-event cycles against the local "
            "Supabase/PostGIS stack."
        )
    )
    parser.add_argument("--feed-url", default=DEFAULT_FEED_URL)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--target-cycle-seconds",
        type=float,
        default=DEFAULT_TARGET_CYCLE_SECONDS,
    )
    return parser.parse_args()


async def run_benchmark(args: argparse.Namespace) -> dict[str, object]:
    if type(args.iterations) is not int or args.iterations <= 0:
        raise ValueError("iterations must be positive")
    if type(args.batch_size) is not int or args.batch_size <= 0:
        raise ValueError("batch-size must be positive")
    if not math.isfinite(args.target_cycle_seconds) or args.target_cycle_seconds <= 0:
        raise ValueError("target-cycle-seconds must be finite and positive")

    configured_url = os.environ.get("BVG_DATABASE_URL")
    if configured_url is None:
        raise ValueError("BVG_DATABASE_URL is required")
    database_url = validate_local_database_url(configured_url)

    timeout = aiohttp.ClientTimeout(total=30)
    samples = []
    pool = await asyncpg.create_pool(
        dsn=database_url,
        min_size=1,
        max_size=1,
        command_timeout=120,
        server_settings={"application_name": "bvg_p7_cycle_benchmark"},
    )
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for _ in range(args.iterations):
                source = TimedSource(AiohttpGtfsRealtimeSource(session, args.feed_url))
                connection = TimedQueryConnection(pool)
                serializer = TimedPositionEventSerializer()
                publisher = JsonMeasurementPublisher()
                estimator = TimedTripPositionEstimator(
                    PostgisTripPositionEstimator(
                        connection,
                        batch_size=args.batch_size,
                    )
                )
                samples.append(
                    await measure_worker_cycle(
                        source=source,
                        estimator=estimator,
                        connection=connection,
                        serializer=serializer,
                        publisher=publisher,
                        observed_at=datetime.now(UTC),
                    )
                )
    finally:
        await pool.close()

    return {
        "benchmark": "p7_realtime_cycle",
        "scenario": "full_download_per_cycle",
        "etag_policy": "new_source_each_iteration_no_conditional_requests",
        "sampling": "sequential_cycles_not_sustained_load",
        **build_summary(
            tuple(samples),
            batch_size=args.batch_size,
            target_cycle_seconds=args.target_cycle_seconds,
        ),
    }


def main() -> int:
    try:
        summary = asyncio.run(run_benchmark(parse_args()))
    except Exception as error:
        print(
            json.dumps(
                {
                    "benchmark": "p7_realtime_cycle",
                    "passed": False,
                    "error_type": type(error).__name__,
                    "message": "benchmark failed before producing a verified summary",
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    print(json.dumps(summary, separators=(",", ":"), sort_keys=True))
    return 0 if summary["passed"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
