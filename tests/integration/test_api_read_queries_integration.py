from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import asyncpg
import pytest

from bvg_radar.api.repository import fetch_route_path_row, fetch_stop_rows

pytestmark = pytest.mark.integration


async def _exercise_route_path_query(database_url: str) -> None:
    connection = await asyncpg.connect(database_url, command_timeout=30)
    try:
        route_id = await connection.fetchval(
            """
            SELECT route.route_id
            FROM gtfs.routes AS route
            WHERE EXISTS (
                SELECT 1
                FROM gtfs.trips AS trip
                JOIN gtfs.route_shapes_geom AS shape USING (shape_id)
                WHERE trip.route_id = route.route_id
                  AND EXISTS (
                      SELECT 1
                      FROM gtfs.stop_times AS stop_time
                      JOIN gtfs.stops AS stop USING (stop_id)
                      WHERE stop_time.trip_id = trip.trip_id
                        AND stop.geom IS NOT NULL
                  )
            )
            ORDER BY route.route_id
            LIMIT 1
            """
        )
        assert route_id is not None

        row = await fetch_route_path_row(connection, route_id)
        assert row is not None
        shapes: list[dict[str, Any]] = json.loads(row["shapes"])
        stops: list[dict[str, Any]] = json.loads(row["stops"])
        assert row["route_id"] == route_id
        assert 0 < len(shapes) <= 3
        assert all(shape["geojson"]["type"] == "LineString" for shape in shapes)
        assert all(len(shape["geojson"]["coordinates"]) >= 2 for shape in shapes)
        assert stops
        assert [stop["stop_sequence"] for stop in stops] == sorted(
            stop["stop_sequence"] for stop in stops
        )
    finally:
        await connection.close()


async def _exercise_stop_modes_query(database_url: str) -> None:
    connection = await asyncpg.connect(database_url, command_timeout=30)
    try:
        rows = await fetch_stop_rows(
            connection,
            bbox=(13.3, 52.4, 13.5, 52.6),
            modes=["tram"],
            limit=20,
        )
        assert 0 < len(rows) <= 20
        assert all("tram" in row["modes"] for row in rows)
        assert all(13.3 <= row["lon"] <= 13.5 for row in rows)
        assert all(52.4 <= row["lat"] <= 52.6 for row in rows)
    finally:
        await connection.close()


def test_route_path_query_returns_real_shapes_and_ordered_stops() -> None:
    database_url = os.environ.get("BVG_DATABASE_URL")
    if not database_url:
        pytest.skip("set BVG_DATABASE_URL to verify the local GTFS route-path query")

    asyncio.run(_exercise_route_path_query(database_url))


def test_stop_modes_query_uses_real_postgis_and_materialized_modes() -> None:
    database_url = os.environ.get("BVG_DATABASE_URL")
    if not database_url:
        pytest.skip("set BVG_DATABASE_URL to verify local PostGIS stop-mode queries")

    asyncio.run(_exercise_stop_modes_query(database_url))
