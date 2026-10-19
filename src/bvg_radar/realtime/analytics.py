"""Pure helpers and ports for sampled route punctuality analytics."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, TypedDict

import asyncpg

from .contracts import EstimatedVehiclePosition

PUNCTUALITY_THRESHOLD_SECONDS = 60
UNKNOWN_VEHICLE_CATEGORY = "unknown"


class RouteObservationRow(TypedDict):
    route_id: str
    vehicle_category: str
    samples: int
    on_time: int
    late: int
    sum_delay_seconds: int


class RouteAnalyticsRecorder(Protocol):
    async def record_cycle(
        self,
        cycle_id: str,
        observed_at: datetime,
        rows: Sequence[RouteObservationRow],
    ) -> bool: ...


class AsyncpgRouteAnalyticsRecorder:
    """Persist one accepted vehicle snapshot through the analytics SQL API."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def record_cycle(
        self,
        cycle_id: str,
        observed_at: datetime,
        rows: Sequence[RouteObservationRow],
    ) -> bool:
        payload = json.dumps(list(rows), separators=(",", ":"))
        async with self._pool.acquire() as connection:
            inserted = await connection.fetchval(
                """
                SELECT analytics.record_route_observations(
                    $1::uuid, $2::timestamptz, $3::jsonb
                )
                """,
                cycle_id,
                observed_at,
                payload,
            )
        return bool(inserted)


def aggregate_route_observations(
    positions: Sequence[EstimatedVehiclePosition],
) -> tuple[RouteObservationRow, ...]:
    """Aggregate observed delays once per estimated vehicle in an accepted cycle.

    Positions without a delay or a usable route identifier are excluded. The
    on-time boundary is inclusive at 60 seconds; only delays strictly above it
    count as late.
    """
    totals: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for position in positions:
        delay = position.delay_seconds
        route_id = position.route_id.strip()
        if delay is None or not route_id:
            continue
        category = position.vehicle_category or UNKNOWN_VEHICLE_CATEGORY
        values = totals[(route_id, category)]
        values[0] += 1
        values[1] += int(delay <= PUNCTUALITY_THRESHOLD_SECONDS)
        values[2] += int(delay > PUNCTUALITY_THRESHOLD_SECONDS)
        values[3] += delay

    return tuple(
        {
            "route_id": route_id,
            "vehicle_category": category,
            "samples": counts[0],
            "on_time": counts[1],
            "late": counts[2],
            "sum_delay_seconds": counts[3],
        }
        for (route_id, category), counts in sorted(totals.items())
    )
