from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import date
from decimal import Decimal

import asyncpg
import pytest

from bvg_radar.api.repository import fetch_daily_punctuality_row

pytestmark = pytest.mark.integration


async def _exercise_daily_punctuality_sql(database_url: str) -> None:
    connection = await asyncpg.connect(database_url, command_timeout=30)
    transaction = connection.transaction()
    await transaction.start()
    try:
        service_day = date(2026, 10, 18)
        punctual_route = f"api-punctual-{uuid.uuid4()}"
        late_route = f"api-late-{uuid.uuid4()}"
        low_sample_route = f"api-low-sample-{uuid.uuid4()}"
        await connection.executemany(
            """
            INSERT INTO analytics.route_daily_punctuality (
                service_day, route_id, vehicle_category, samples, on_time, late,
                sum_delay_seconds, on_time_ratio, mean_delay_seconds
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            """,
            [
                (
                    service_day,
                    punctual_route,
                    "bus",
                    100,
                    95,
                    5,
                    825,
                    Decimal("0.95"),
                    Decimal("8.25"),
                ),
                (
                    service_day,
                    late_route,
                    "tram",
                    80,
                    44,
                    36,
                    4896,
                    Decimal("0.55"),
                    Decimal("61.20"),
                ),
                (
                    service_day,
                    low_sample_route,
                    "bus",
                    10,
                    5,
                    5,
                    300,
                    Decimal("0.50"),
                    Decimal("30.00"),
                ),
            ],
        )

        result = await fetch_daily_punctuality_row(
            connection,
            service_day,
            limit=1,
            min_samples=40,
        )
        assert result is not None
        most = json.loads(result["most_punctual"])
        least = json.loads(result["least_punctual"])
        totals = json.loads(result["totals"])
        assert most[0]["route_id"] == punctual_route
        assert most[0]["route_short_name"] is None
        assert least[0]["route_id"] == late_route
        assert totals == {
            "routes": 3,
            "route_categories": 3,
            "samples": 190,
            "on_time": 144,
            "late": 46,
        }
        ranked_route_ids = {
            row["route_id"]
            for ranking in (most, least)
            for row in ranking
        }
        assert low_sample_route not in ranked_route_ids

        one_qualified_line = await fetch_daily_punctuality_row(
            connection,
            service_day,
            limit=10,
            min_samples=90,
        )
        assert one_qualified_line is not None
        top = json.loads(one_qualified_line["most_punctual"])
        bottom = json.loads(one_qualified_line["least_punctual"])
        assert [row["route_id"] for row in top] == [punctual_route]
        assert [row["route_id"] for row in bottom] == [punctual_route]
    finally:
        await transaction.rollback()
        await connection.close()


def test_daily_punctuality_query_ranks_rollups_and_rolls_back_fixtures() -> None:
    database_url = os.environ.get("BVG_DATABASE_URL")
    if not database_url:
        pytest.skip("set BVG_DATABASE_URL to verify the local daily analytics query")

    asyncio.run(_exercise_daily_punctuality_sql(database_url))
