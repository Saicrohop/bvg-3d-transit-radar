from __future__ import annotations

import asyncio
import json
import logging
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg
from fastapi import APIRouter, HTTPException, Path, Query, Request, Response

from .cache import RoutePathCache
from .models import (
    DailyPunctualityResponse,
    RouteListResponse,
    RoutePathResponse,
    StopsResponse,
)
from .repository import (
    ReadPool,
    fetch_daily_punctuality_row,
    fetch_route_path_row,
    fetch_route_rows,
    fetch_stop_rows,
)
from ..realtime.vehicle_category import classify_berlin_vehicle

logger = logging.getLogger(__name__)
router = APIRouter()
CACHE_CONTROL = "public, max-age=60"
API_QUERY_TIMEOUT_SECONDS = 5.0
SUPPORTED_STOP_MODES = frozenset({"u_bahn", "s_bahn", "bus", "tram", "regional"})
MAX_BBOX_SPAN_DEGREES = 5.0


def _parse_bbox(value: str) -> tuple[float, float, float, float]:
    try:
        coordinates = tuple(float(part.strip()) for part in value.split(","))
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail="bbox must contain four finite coordinates",
        ) from error
    if len(coordinates) != 4 or not all(math.isfinite(item) for item in coordinates):
        raise HTTPException(
            status_code=422,
            detail="bbox must contain four finite coordinates",
        )
    west, south, east, north = coordinates
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise HTTPException(status_code=422, detail="bbox coordinates are out of order or range")
    if east - west > MAX_BBOX_SPAN_DEGREES or north - south > MAX_BBOX_SPAN_DEGREES:
        raise HTTPException(status_code=422, detail="bbox spans at most five degrees per side")
    return west, south, east, north


def _parse_modes(value: str | None) -> list[str] | None:
    if value is None or not value.strip():
        return None
    modes = [item.strip().lower() for item in value.split(",")]
    if any(not mode or mode not in SUPPORTED_STOP_MODES for mode in modes):
        allowed = ", ".join(sorted(SUPPORTED_STOP_MODES))
        raise HTTPException(status_code=422, detail=f"modes must be selected from: {allowed}")
    return sorted(set(modes))


def _get_database_pool(request: Request) -> ReadPool:
    pool = getattr(request.app.state, "database_pool", None)
    if pool is None:
        raise HTTPException(
            status_code=503,
            detail="Transit data is temporarily unavailable",
        )
    return pool


def _active_vehicle_counts(snapshot: object) -> Counter[str]:
    if not isinstance(snapshot, Mapping):
        return Counter()
    positions = snapshot.get("positions")
    if not isinstance(positions, list):
        return Counter()
    return Counter(
        position["route_id"]
        for position in positions
        if isinstance(position, Mapping)
        and isinstance(position.get("route_id"), str)
    )


def _get_route_path_cache(request: Request) -> RoutePathCache:
    cache = getattr(request.app.state, "route_path_cache", None)
    if cache is None:
        cache = RoutePathCache()
        request.app.state.route_path_cache = cache
    return cache


def _decode_json_array(value: object) -> list[dict[str, Any]]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, list) or any(
        not isinstance(item, dict) for item in decoded
    ):
        raise ValueError("database returned an invalid route payload")
    return decoded


def _decode_json_object(value: object) -> dict[str, Any]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise ValueError("database returned an invalid totals payload")
    return decoded


def _parse_gtfs_time(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    parts = value.split(":")
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = (int(part) for part in parts)
    except ValueError:
        return None
    if hours < 0 or not 0 <= minutes < 60 or not 0 <= seconds < 60:
        return None
    return hours * 3600 + minutes * 60 + seconds


def _scheduled_offsets(
    stops: Sequence[Mapping[str, Any]],
) -> list[dict[str, int | None]]:
    if not stops:
        return []
    base_time = _parse_gtfs_time(stops[0].get("arrival_time"))
    return [
        {
            "stop_sequence": int(stop["stop_sequence"]),
            "arrival_offset_s": (
                None
                if base_time is None
                or (arrival_time := _parse_gtfs_time(stop.get("arrival_time"))) is None
                else arrival_time - base_time
            ),
        }
        for stop in stops
    ]


def _route_bounds(shapes: Sequence[Mapping[str, Any]]) -> tuple[float, float, float, float] | None:
    coordinates = [
        point
        for shape in shapes
        for point in shape["geojson"]["coordinates"]
        if isinstance(point, (list, tuple)) and len(point) >= 2
    ]
    if not coordinates:
        return None
    longitudes = [float(point[0]) for point in coordinates]
    latitudes = [float(point[1]) for point in coordinates]
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)


@router.get("/api/routes", response_model=RouteListResponse)
async def list_routes(request: Request, response: Response) -> RouteListResponse:
    response.headers["Cache-Control"] = CACHE_CONTROL
    pool = _get_database_pool(request)
    hub = getattr(request.app.state, "position_hub", None)
    snapshot = getattr(hub, "latest_snapshot", None)
    active_counts = _active_vehicle_counts(snapshot)

    try:
        async with asyncio.timeout(API_QUERY_TIMEOUT_SECONDS):
            rows = await fetch_route_rows(pool)
    except TimeoutError as error:
        raise HTTPException(
            status_code=504,
            detail="Transit data query timed out",
        ) from error
    except (asyncpg.PostgresError, asyncpg.InterfaceError) as error:
        logger.warning("Route catalogue query failed (%s)", type(error).__name__)
        raise HTTPException(
            status_code=503,
            detail="Transit data is temporarily unavailable",
        ) from error

    return RouteListResponse(
        routes=[
            {
                "route_id": str(row["route_id"]),
                "route_short_name": row["route_short_name"],
                "route_type": int(row["route_type"]),
                "vehicle_category": classify_berlin_vehicle(
                    int(row["route_type"]),
                    row["route_short_name"],
                ),
                "active_vehicles": active_counts.get(str(row["route_id"]), 0),
            }
            for row in rows
        ]
    )


@router.get("/api/routes/{route_id}/path", response_model=RoutePathResponse)
async def get_route_path(
    request: Request,
    response: Response,
    route_id: str = Path(pattern=r"^[A-Za-z0-9._:-]{1,128}$"),
) -> RoutePathResponse:
    response.headers["Cache-Control"] = CACHE_CONTROL
    cache = _get_route_path_cache(request)
    cached = cache.get(route_id)
    if cached is not None:
        return RoutePathResponse.model_validate(cached)

    pool = _get_database_pool(request)
    try:
        async with asyncio.timeout(API_QUERY_TIMEOUT_SECONDS):
            row = await fetch_route_path_row(pool, route_id)
    except TimeoutError as error:
        raise HTTPException(
            status_code=504,
            detail="Transit data query timed out",
        ) from error
    except (asyncpg.PostgresError, asyncpg.InterfaceError) as error:
        logger.warning("Route path query failed (%s)", type(error).__name__)
        raise HTTPException(
            status_code=503,
            detail="Transit data is temporarily unavailable",
        ) from error

    if row is None:
        raise HTTPException(status_code=404, detail="Route not found")

    shapes = _decode_json_array(row["shapes"])
    raw_stops = _decode_json_array(row["stops"])
    stops = [
        {
            "stop_sequence": int(stop["stop_sequence"]),
            "stop_id": str(stop["stop_id"]),
            "stop_name": stop["stop_name"],
            "lon": float(stop["lon"]),
            "lat": float(stop["lat"]),
        }
        for stop in raw_stops
    ]
    payload = RoutePathResponse(
        route_id=str(row["route_id"]),
        route_short_name=row["route_short_name"],
        vehicle_category=classify_berlin_vehicle(
            int(row["route_type"]),
            row["route_short_name"],
        ),
        shapes=shapes,
        stops=stops,
        scheduled_offsets=_scheduled_offsets(raw_stops),
        bounds=_route_bounds(shapes),
    )
    cache.set(route_id, payload.model_dump(mode="json"))
    return payload


@router.get("/api/stops", response_model=StopsResponse)
async def get_stops(
    request: Request,
    response: Response,
    bbox: str = Query(...),
    limit: int = Query(500, ge=1, le=500),
    modes: str | None = Query(None),
) -> StopsResponse:
    response.headers["Cache-Control"] = CACHE_CONTROL
    parsed_bbox = _parse_bbox(bbox)
    parsed_modes = _parse_modes(modes)
    pool = _get_database_pool(request)

    try:
        async with asyncio.timeout(API_QUERY_TIMEOUT_SECONDS):
            rows = await fetch_stop_rows(pool, parsed_bbox, parsed_modes, limit)
    except TimeoutError as error:
        raise HTTPException(
            status_code=504,
            detail="Transit data query timed out",
        ) from error
    except (asyncpg.PostgresError, asyncpg.InterfaceError) as error:
        logger.warning("Stop catalogue query failed (%s)", type(error).__name__)
        raise HTTPException(
            status_code=503,
            detail="Transit data is temporarily unavailable",
        ) from error

    return StopsResponse(
        bbox=parsed_bbox,
        stops=[
            {
                "stop_id": str(row["stop_id"]),
                "name": row["stop_name"],
                "location_type": int(row["location_type"]),
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "modes": sorted(set(row["modes"] or [])),
            }
            for row in rows
        ],
    )


@router.get(
    "/api/punctuality/daily",
    response_model=DailyPunctualityResponse,
)
async def get_daily_punctuality(
    request: Request,
    response: Response,
    date_value: date | None = Query(None, alias="date"),
    limit: int = Query(10, ge=1, le=100),
    min_samples: int = Query(40, ge=1, le=1_000_000),
) -> DailyPunctualityResponse:
    response.headers["Cache-Control"] = CACHE_CONTROL
    service_day = date_value or datetime.now(ZoneInfo("Europe/Berlin")).date()
    pool = _get_database_pool(request)

    try:
        async with asyncio.timeout(API_QUERY_TIMEOUT_SECONDS):
            row = await fetch_daily_punctuality_row(
                pool,
                service_day,
                limit,
                min_samples,
            )
    except TimeoutError as error:
        raise HTTPException(
            status_code=504,
            detail="Transit data query timed out",
        ) from error
    except (asyncpg.PostgresError, asyncpg.InterfaceError) as error:
        logger.warning("Daily punctuality query failed (%s)", type(error).__name__)
        raise HTTPException(
            status_code=503,
            detail="Transit data is temporarily unavailable",
        ) from error

    if row is None:
        most_punctual: list[dict[str, Any]] = []
        least_punctual: list[dict[str, Any]] = []
        totals: dict[str, Any] = {
            "routes": 0,
            "route_categories": 0,
            "samples": 0,
            "on_time": 0,
            "late": 0,
        }
    else:
        most_punctual = _decode_json_array(row["most_punctual"])
        least_punctual = _decode_json_array(row["least_punctual"])
        totals = _decode_json_object(row["totals"])

    return DailyPunctualityResponse(
        date=service_day,
        most_punctual=most_punctual,
        least_punctual=least_punctual,
        totals=totals,
    )
