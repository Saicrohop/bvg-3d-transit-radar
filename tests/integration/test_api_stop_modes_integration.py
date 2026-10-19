from __future__ import annotations

import asyncio
import os

import asyncpg
import pytest

pytestmark = pytest.mark.integration


async def _verify_stop_vehicle_modes_view(database_url: str) -> None:
    connection = await asyncpg.connect(database_url, command_timeout=30)
    try:
        tram_stop = await connection.fetchrow(
            """
            SELECT stop_id, vehicle_category
            FROM gtfs.stop_vehicle_modes
            WHERE vehicle_category = 'tram'
            ORDER BY stop_id
            LIMIT 1
            """
        )
        station_mode = await connection.fetchrow(
            """
            SELECT station.stop_id, modes.vehicle_category
            FROM gtfs.stops AS station
            JOIN gtfs.stop_vehicle_modes AS modes
                ON modes.stop_id = station.stop_id
            WHERE station.location_type = 1
            ORDER BY station.stop_id, modes.vehicle_category
            LIMIT 1
            """
        )
    finally:
        await connection.close()

    assert tram_stop is not None
    assert tram_stop["vehicle_category"] == "tram"
    assert station_mode is not None


def test_gtfs_stop_vehicle_modes_covers_tram_stops_and_parent_stations() -> None:
    database_url = os.environ.get("BVG_DATABASE_URL")
    if not database_url:
        pytest.skip("set BVG_DATABASE_URL to verify the local GTFS stop-mode index")

    asyncio.run(_verify_stop_vehicle_modes_view(database_url))
