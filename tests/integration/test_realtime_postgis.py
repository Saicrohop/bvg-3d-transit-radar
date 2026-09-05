import asyncio
import math
import os
from datetime import timedelta
from urllib.parse import urlsplit

import asyncpg
import pytest

from bvg_radar.realtime.models import StopTimeUpdate, TripUpdate
from bvg_radar.realtime.postgis import PostgisTripPositionEstimator

pytestmark = pytest.mark.integration

EXPECTED_LOCAL_DB_PORT = 54022
CANDIDATE_SEGMENT_SQL = """
SELECT
    stop_time.trip_id,
    trip.route_id,
    trip.shape_id,
    stop_time.stop_id AS previous_stop_id,
    next_stop.stop_id AS next_stop_id,
    next_stop.stop_sequence AS next_stop_sequence,
    CURRENT_DATE AS service_date,
    (
        CURRENT_DATE
        + gtfs.gtfs_time_to_interval(stop_time.departure_time)
    ) AT TIME ZONE 'Europe/Berlin' AS departure_at,
    (
        CURRENT_DATE
        + gtfs.gtfs_time_to_interval(next_stop.arrival_time)
    ) AT TIME ZONE 'Europe/Berlin' AS next_arrival_at
FROM gtfs.stop_times AS stop_time
JOIN gtfs.trips AS trip ON trip.trip_id = stop_time.trip_id
JOIN LATERAL (
    SELECT
        following.stop_id,
        following.stop_sequence,
        following.shape_fraction,
        following.arrival_time
    FROM gtfs.stop_times AS following
    WHERE following.trip_id = stop_time.trip_id
      AND following.stop_sequence > stop_time.stop_sequence
    ORDER BY following.stop_sequence
    LIMIT 1
) AS next_stop ON TRUE
WHERE stop_time.shape_fraction IS NOT NULL
  AND next_stop.shape_fraction > stop_time.shape_fraction
  AND gtfs.gtfs_time_to_interval(next_stop.arrival_time)
      - gtfs.gtfs_time_to_interval(stop_time.departure_time)
      >= INTERVAL '2 minutes'
ORDER BY stop_time.trip_id, stop_time.stop_sequence
LIMIT 1;
"""


def _local_database_url() -> str:
    database_url = os.environ.get("BVG_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "BVG_DATABASE_URL is not set; local PostGIS integration was not run"
        )

    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        pytest.fail("BVG_DATABASE_URL must be a PostgreSQL URL")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("PostGIS integration is restricted to a loopback database")
    if parsed.port != EXPECTED_LOCAL_DB_PORT:
        pytest.fail(
            f"PostGIS integration requires the project-local port "
            f"{EXPECTED_LOCAL_DB_PORT}"
        )
    return database_url


async def _exercise_real_postgis_adapter(database_url: str) -> None:
    connection = await asyncpg.connect(dsn=database_url, command_timeout=60)
    try:
        async with connection.transaction(readonly=True):
            candidate = await connection.fetchrow(CANDIDATE_SEGMENT_SQL)
            assert candidate is not None, "no safe segment exists in the current GTFS snapshot"

            observed_at = candidate["departure_at"] + (
                candidate["next_arrival_at"] - candidate["departure_at"]
            ) / 2
            update = TripUpdate(
                entity_id="postgis-integration-probe",
                trip_id=str(candidate["trip_id"]),
                route_id=str(candidate["route_id"]),
                service_date=candidate["service_date"],
                trip_update_timestamp=int(observed_at.timestamp()),
                stop_time_updates=(
                    StopTimeUpdate(
                        stop_sequence=int(candidate["next_stop_sequence"]),
                        stop_id=str(candidate["next_stop_id"]),
                        arrival_time=None,
                        arrival_delay_seconds=120,
                        departure_time=None,
                        departure_delay_seconds=None,
                    ),
                ),
            )

            result = await PostgisTripPositionEstimator(connection).estimate(
                update,
                observed_at,
            )

            assert result is not None
            assert result.entity_id == "postgis-integration-probe"
            assert result.trip_id == candidate["trip_id"]
            assert result.route_id == candidate["route_id"]
            assert result.shape_id == candidate["shape_id"]
            assert result.previous_stop_id == candidate["previous_stop_id"]
            assert result.next_stop_id == candidate["next_stop_id"]
            assert result.delay_seconds == 120
            assert result.estimated_next_arrival == candidate[
                "next_arrival_at"
            ] + timedelta(seconds=120)
            assert result.observed_at == observed_at
            assert math.isfinite(result.longitude)
            assert math.isfinite(result.latitude)
            assert math.isfinite(result.bearing_degrees)
            assert math.isfinite(result.speed_mps)
            assert -180.0 <= result.longitude <= 180.0
            assert -90.0 <= result.latitude <= 90.0
            assert 0.0 <= result.bearing_degrees < 360.0
            assert result.speed_mps >= 0.0
    finally:
        await connection.close()


def test_realtime_adapter_estimates_a_position_with_local_postgis() -> None:
    asyncio.run(_exercise_real_postgis_adapter(_local_database_url()))
