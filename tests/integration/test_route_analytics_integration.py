import asyncio
import json
import os
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import asyncpg
import pytest

from bvg_radar.realtime.benchmark import validate_local_database_url

pytestmark = pytest.mark.integration
TEST_SERVICE_DAY = date(2099, 1, 15)


async def _exercise_route_analytics(database_url: str) -> None:
    connection = await asyncpg.connect(dsn=database_url, command_timeout=30)
    cycle_id = uuid.uuid4()
    route_on_time = f"analytics-test-on-time-{cycle_id}"
    route_late = f"analytics-test-late-{cycle_id}"
    observed_at = datetime(2099, 1, 15, 12, 7, tzinfo=timezone.utc)
    rows = [
        {
            "route_id": route_on_time,
            "vehicle_category": "tram",
            "samples": 2,
            "on_time": 2,
            "late": 0,
            "sum_delay_seconds": 30,
        },
        {
            "route_id": route_late,
            "vehicle_category": "bus",
            "samples": 2,
            "on_time": 1,
            "late": 1,
            "sum_delay_seconds": 121,
        },
    ]
    try:
        await connection.execute("BEGIN")
        inserted = await connection.fetchval(
            "SELECT analytics.record_route_observations($1, $2, $3::jsonb)",
            cycle_id,
            observed_at,
            json.dumps(rows),
        )
        duplicate = await connection.fetchval(
            "SELECT analytics.record_route_observations($1, $2, $3::jsonb)",
            cycle_id,
            observed_at,
            json.dumps(rows),
        )
        second_cycle_id = uuid.uuid4()
        second_observed_at = datetime(2099, 1, 15, 12, 22, tzinfo=timezone.utc)
        second_inserted = await connection.fetchval(
            "SELECT analytics.record_route_observations($1, $2, $3::jsonb)",
            second_cycle_id,
            second_observed_at,
            json.dumps(
                [
                    {
                        "route_id": route_on_time,
                        "vehicle_category": "tram",
                        "samples": 8,
                        "on_time": 4,
                        "late": 4,
                        "sum_delay_seconds": 1200,
                    }
                ]
            ),
        )
        bucket_rows = await connection.fetch(
            """
            SELECT route_id, vehicle_category, samples, on_time, late,
                   sum_delay_seconds, service_day, bucket_start
            FROM analytics.route_observation_windows
            WHERE route_id = ANY($1::text[])
            ORDER BY route_id
            """,
            [route_on_time, route_late],
        )
        await connection.execute(
            "SELECT analytics.refresh_route_daily_punctuality($1)",
            TEST_SERVICE_DAY,
        )
        daily_rows = await connection.fetch(
            """
            SELECT route_id, samples, on_time, late, on_time_ratio, mean_delay_seconds
            FROM analytics.route_daily_punctuality
            WHERE route_id = ANY($1::text[])
            ORDER BY route_id
            """,
            [route_on_time, route_late],
        )
        default_ranking_rows = await connection.fetch(
            """
            SELECT route_id
            FROM analytics.refresh_daily_line_ranking($1)
            WHERE route_id = ANY($2::text[])
            """,
            TEST_SERVICE_DAY,
            [route_on_time, route_late],
        )
        ranking_rows = await connection.fetch(
            """
            SELECT direction, rank_position, route_id, samples, on_time_ratio
            FROM analytics.refresh_daily_line_ranking($1, 1, 10)
            WHERE route_id = ANY($2::text[])
            ORDER BY direction, rank_position
            """,
            TEST_SERVICE_DAY,
            [route_on_time, route_late],
        )
        assert inserted is True
        assert duplicate is False
        assert second_inserted is True
        assert len(bucket_rows) == 3
        assert {row["service_day"] for row in bucket_rows} == {observed_at.date()}
        assert {row["bucket_start"] for row in bucket_rows} == {
            datetime(2099, 1, 15, 12, 0, tzinfo=timezone.utc),
            datetime(2099, 1, 15, 12, 15, tzinfo=timezone.utc),
        }
        assert next(row for row in bucket_rows if row["route_id"] == route_late)[
            "late"
        ] == 1
        punctual_route = next(
            row for row in daily_rows if row["route_id"] == route_on_time
        )
        assert punctual_route["samples"] == 10
        assert punctual_route["on_time"] == 6
        assert punctual_route["late"] == 4
        assert punctual_route["on_time_ratio"] == Decimal("0.600000")
        assert punctual_route["mean_delay_seconds"] == Decimal("123.00")
        assert default_ranking_rows == []
        ranked_routes = {
            direction: [
                row["route_id"]
                for row in ranking_rows
                if row["direction"] == direction
            ]
            for direction in ("least_punctual", "most_punctual")
        }
        assert ranked_routes == {
            "least_punctual": [route_late, route_on_time],
            "most_punctual": [route_on_time, route_late],
        }
        assert all(
            row["samples"] == (10 if row["route_id"] == route_on_time else 2)
            for row in ranking_rows
        )
        service_cycle_id = uuid.uuid4()
        await connection.execute("SET LOCAL ROLE service_role")
        service_role_inserted = await connection.fetchval(
            "SELECT analytics.record_route_observations($1, $2, $3::jsonb)",
            service_cycle_id,
            observed_at,
            json.dumps(
                [
                    {
                        "route_id": f"service-role-{cycle_id}",
                        "vehicle_category": "bus",
                        "samples": 1,
                        "on_time": 1,
                        "late": 0,
                        "sum_delay_seconds": 0,
                    }
                ]
            ),
        )
        await connection.execute("RESET ROLE")
        assert service_role_inserted is True
        public_access = await connection.fetchval(
            """
            SELECT has_table_privilege(
                'anon', 'analytics.route_daily_punctuality', 'SELECT'
            )
                OR has_table_privilege(
                    'authenticated', 'analytics.route_daily_punctuality', 'SELECT'
                )
            """
        )
        assert public_access is False
    finally:
        await connection.execute("ROLLBACK")
        await connection.close()


def test_route_analytics_cycle_dedup_bucket_and_daily_ranking() -> None:
    database_url = os.environ.get("BVG_DATABASE_URL")
    if not database_url:
        pytest.skip("BVG_DATABASE_URL is not set; local analytics SQL was not run")
    asyncio.run(
        _exercise_route_analytics(validate_local_database_url(database_url))
    )


async def _exercise_invalid_rows_do_not_consume_cycle(database_url: str) -> None:
    connection = await asyncpg.connect(dsn=database_url, command_timeout=30)
    cycle_id = uuid.uuid4()
    route_id = f"valid-test-route-{cycle_id}"
    observed_at = datetime(2026, 10, 18, 12, 7, tzinfo=timezone.utc)
    try:
        with pytest.raises(asyncpg.InvalidParameterValueError):
            await connection.fetchval(
                "SELECT analytics.record_route_observations($1, $2, $3::jsonb)",
                cycle_id,
                observed_at,
                json.dumps(
                    [
                        {
                            "route_id": "invalid-test-route",
                            "vehicle_category": "not-a-category",
                            "samples": 1,
                            "on_time": 1,
                            "late": 0,
                            "sum_delay_seconds": 0,
                        }
                    ]
                ),
            )

        inserted = await connection.fetchval(
            "SELECT analytics.record_route_observations($1, $2, $3::jsonb)",
            cycle_id,
            observed_at,
            json.dumps(
                [
                    {
                        "route_id": route_id,
                        "vehicle_category": "bus",
                        "samples": 1,
                        "on_time": 1,
                        "late": 0,
                        "sum_delay_seconds": 0,
                    }
                ]
            ),
        )
        assert inserted is True
    finally:
        await connection.execute(
            "DELETE FROM analytics.route_observation_windows WHERE route_id = $1",
            route_id,
        )
        await connection.execute(
            "DELETE FROM analytics.route_observation_cycles WHERE cycle_id = $1",
            cycle_id,
        )
        await connection.close()


def test_invalid_route_observation_is_rejected_without_consuming_cycle() -> None:
    database_url = os.environ.get("BVG_DATABASE_URL")
    if not database_url:
        pytest.skip("BVG_DATABASE_URL is not set; local analytics SQL was not run")
    asyncio.run(
        _exercise_invalid_rows_do_not_consume_cycle(
            validate_local_database_url(database_url)
        )
    )
