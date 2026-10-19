from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from datetime import date
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bvg_radar.api import routes as api_routes
from bvg_radar.api.routes import router


class FakeReadPool:
    def __init__(
        self,
        route_rows: Sequence[dict[str, Any]],
        route_path_row: dict[str, Any] | None = None,
        stop_rows: Sequence[dict[str, Any]] = (),
        daily_row: dict[str, Any] | None = None,
    ) -> None:
        self.route_rows = route_rows
        self.route_path_row = route_path_row
        self.stop_rows = stop_rows
        self.daily_row = daily_row
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.path_calls: list[tuple[str, tuple[object, ...]]] = []
        self.daily_calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch(self, query: str, *arguments: object) -> Sequence[dict[str, Any]]:
        self.calls.append((query, arguments))
        if "FROM gtfs.routes" in query:
            return self.route_rows
        return self.stop_rows

    async def fetchrow(self, query: str, *arguments: object) -> dict[str, Any] | None:
        if "analytics.route_daily_punctuality" in query:
            self.daily_calls.append((query, arguments))
            return self.daily_row
        self.path_calls.append((query, arguments))
        return self.route_path_row


def _create_test_app(pool: FakeReadPool, snapshot: dict[str, Any] | None) -> FastAPI:
    app = FastAPI()
    app.state.database_pool = pool
    app.state.position_hub = SimpleNamespace(latest_snapshot=snapshot)
    app.include_router(router)
    return app


def test_routes_returns_gtfs_metadata_and_active_counts_from_latest_snapshot() -> None:
    pool = FakeReadPool(
        [
            {"route_id": "1879_900", "route_short_name": "1", "route_type": 900},
            {"route_id": "15624_700", "route_short_name": "10", "route_type": 700},
            {"route_id": "unknown_106", "route_short_name": "X1", "route_type": 106},
        ]
    )
    snapshot = {
        "positions": [
            {"route_id": "1879_900"},
            {"route_id": "1879_900"},
            {"route_id": "15624_700"},
            {"route_id": "not-in-static-gtfs"},
        ]
    }

    with TestClient(_create_test_app(pool, snapshot)) as client:
        response = client.get("/api/routes")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60"
    assert response.json() == {
        "routes": [
            {
                "route_id": "1879_900",
                "route_short_name": "1",
                "route_type": 900,
                "vehicle_category": "tram",
                "active_vehicles": 2,
            },
            {
                "route_id": "15624_700",
                "route_short_name": "10",
                "route_type": 700,
                "vehicle_category": "bus",
                "active_vehicles": 1,
            },
            {
                "route_id": "unknown_106",
                "route_short_name": "X1",
                "route_type": 106,
                "vehicle_category": None,
                "active_vehicles": 0,
            },
        ]
    }
    assert len(pool.calls) == 1
    query, arguments = pool.calls[0]
    assert "FROM gtfs.routes" in query
    assert arguments == ()


def test_routes_without_a_snapshot_reports_zero_active_vehicles() -> None:
    pool = FakeReadPool(
        [{"route_id": "1879_900", "route_short_name": "1", "route_type": 900}]
    )

    with TestClient(_create_test_app(pool, None)) as client:
        response = client.get("/api/routes")

    assert response.status_code == 200
    assert response.json()["routes"][0]["active_vehicles"] == 0


def test_route_path_returns_top_shapes_common_stops_offsets_and_60s_cache() -> None:
    route_path_row = {
        "route_id": "1879_900",
        "route_short_name": "1",
        "route_type": 900,
        "shapes": json.dumps(
            [
                {
                    "shape_id": "8160",
                    "trip_count": 62,
                    "geojson": {
                        "type": "LineString",
                        "coordinates": [[13.4, 52.5], [13.45, 52.55]],
                    },
                },
                {
                    "shape_id": "8158",
                    "trip_count": 61,
                    "geojson": {
                        "type": "LineString",
                        "coordinates": [[13.3, 52.4], [13.5, 52.6]],
                    },
                },
            ]
        ),
        "stops": json.dumps(
            [
                {
                    "stop_sequence": 0,
                    "stop_id": "A",
                    "stop_name": "Alpha",
                    "lon": 13.4,
                    "lat": 52.5,
                    "arrival_time": "6:37:36",
                },
                {
                    "stop_sequence": 1,
                    "stop_id": "B",
                    "stop_name": "Bravo",
                    "lon": 13.45,
                    "lat": 52.55,
                    "arrival_time": "6:44:06",
                },
            ]
        ),
    }
    pool = FakeReadPool([], route_path_row)

    with TestClient(_create_test_app(pool, None)) as client:
        first = client.get("/api/routes/1879_900/path")
        second = client.get("/api/routes/1879_900/path")

    assert first.status_code == 200
    assert first.headers["cache-control"] == "public, max-age=60"
    body = first.json()
    assert body["route_id"] == "1879_900"
    assert body["route_short_name"] == "1"
    assert body["vehicle_category"] == "tram"
    assert [shape["shape_id"] for shape in body["shapes"]] == ["8160", "8158"]
    assert body["stops"] == [
        {"stop_sequence": 0, "stop_id": "A", "stop_name": "Alpha", "lon": 13.4, "lat": 52.5},
        {"stop_sequence": 1, "stop_id": "B", "stop_name": "Bravo", "lon": 13.45, "lat": 52.55},
    ]
    assert body["scheduled_offsets"] == [
        {"stop_sequence": 0, "arrival_offset_s": 0},
        {"stop_sequence": 1, "arrival_offset_s": 390},
    ]
    assert body["bounds"] == [13.3, 52.4, 13.5, 52.6]
    assert second.json() == body
    assert len(pool.path_calls) == 1
    assert pool.path_calls[0][1] == ("1879_900",)


def test_route_path_returns_404_for_unknown_route_and_422_for_invalid_id() -> None:
    pool = FakeReadPool([], None)

    with TestClient(_create_test_app(pool, None)) as client:
        missing = client.get("/api/routes/not_found/path")
        invalid = client.get("/api/routes/bad%20route/path")

    assert missing.status_code == 404
    assert invalid.status_code == 422
    assert len(pool.path_calls) == 1


def test_stops_applies_validated_bbox_modes_and_limit() -> None:
    pool = FakeReadPool(
        [],
        stop_rows=[
            {
                "stop_id": "900360132",
                "stop_name": "Frankfurt (Oder), Stadion",
                "location_type": 1,
                "lat": 52.333987,
                "lon": 14.554727,
                "modes": ["tram", "bus", "tram"],
            }
        ],
    )

    with TestClient(_create_test_app(pool, None)) as client:
        response = client.get(
            "/api/stops",
            params={
                "bbox": "14.5,52.3,14.6,52.4",
                "limit": 10,
                "modes": "tram,bus",
            },
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60"
    assert response.json() == {
        "bbox": [14.5, 52.3, 14.6, 52.4],
        "stops": [
            {
                "stop_id": "900360132",
                "name": "Frankfurt (Oder), Stadion",
                "location_type": 1,
                "lat": 52.333987,
                "lon": 14.554727,
                "modes": ["bus", "tram"],
            }
        ],
    }
    query, arguments = pool.calls[0]
    assert "st_makeenvelope" in query.lower()
    assert arguments == (14.5, 52.3, 14.6, 52.4, ["bus", "tram"], 10)


def test_stops_returns_empty_array_for_an_unserved_bbox() -> None:
    pool = FakeReadPool([])

    with TestClient(_create_test_app(pool, None)) as client:
        response = client.get("/api/stops?bbox=13.3,52.4,13.5,52.6")

    assert response.status_code == 200
    assert response.json()["stops"] == []
    assert len(pool.calls) == 1


def test_stops_rejects_invalid_bbox_modes_and_limits_before_querying() -> None:
    pool = FakeReadPool([])
    invalid_queries = [
        {"bbox": "13.5,52.4,13.3,52.6"},
        {"bbox": "13.3,52.4,13.5"},
        {"bbox": "13.3,52.4,nan,52.6"},
        {"bbox": "13.3,52.4,13.5,inf"},
        {"bbox": "10,52,15.1,53"},
        {"bbox": "13.3,52.4,13.5,52.6", "modes": "spaceship"},
        {"bbox": "13.3,52.4,13.5,52.6", "limit": "501"},
        {"bbox": "-180,-90,180,90"},
    ]

    with TestClient(_create_test_app(pool, None)) as client:
        responses = [client.get("/api/stops", params=params) for params in invalid_queries]

    assert [response.status_code for response in responses] == [422] * len(
        invalid_queries
    )
    assert pool.calls == []


def test_daily_punctuality_returns_rankings_and_totals_without_writes() -> None:
    pool = FakeReadPool(
        [],
        daily_row={
            "most_punctual": json.dumps(
                [
                    {
                        "position": 1,
                        "route_id": "15624_700",
                        "route_short_name": "10",
                        "vehicle_category": "bus",
                        "samples": 400,
                        "on_time_ratio": 0.95,
                        "mean_delay_seconds": 8.25,
                    }
                ]
            ),
            "least_punctual": json.dumps(
                [
                    {
                        "position": 1,
                        "route_id": "1879_900",
                        "route_short_name": "1",
                        "vehicle_category": "tram",
                        "samples": 80,
                        "on_time_ratio": 0.55,
                        "mean_delay_seconds": 61.2,
                    }
                ]
            ),
            "totals": json.dumps(
                {
                    "routes": 2,
                    "route_categories": 2,
                    "samples": 480,
                    "on_time": 424,
                    "late": 56,
                }
            ),
        },
    )

    with TestClient(_create_test_app(pool, None)) as client:
        response = client.get(
            "/api/punctuality/daily",
            params={"date": "2026-10-18", "limit": 10, "min_samples": 80},
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60"
    assert response.json() == {
        "date": "2026-10-18",
        "most_punctual": [
            {
                "position": 1,
                "route_id": "15624_700",
                "route_short_name": "10",
                "vehicle_category": "bus",
                "samples": 400,
                "on_time_ratio": 0.95,
                "mean_delay_seconds": 8.25,
            }
        ],
        "least_punctual": [
            {
                "position": 1,
                "route_id": "1879_900",
                "route_short_name": "1",
                "vehicle_category": "tram",
                "samples": 80,
                "on_time_ratio": 0.55,
                "mean_delay_seconds": 61.2,
            }
        ],
        "totals": {
            "routes": 2,
            "route_categories": 2,
            "samples": 480,
            "on_time": 424,
            "late": 56,
        },
    }
    query, arguments = pool.daily_calls[0]
    assert "SELECT" in query.upper()
    assert "REFRESH" not in query.upper()
    assert arguments == (date(2026, 10, 18), 10, 80)


def test_daily_punctuality_returns_empty_results_when_day_has_no_rollup() -> None:
    pool = FakeReadPool(
        [],
        daily_row={
            "most_punctual": "[]",
            "least_punctual": "[]",
            "totals": json.dumps(
                {
                    "routes": 0,
                    "route_categories": 0,
                    "samples": 0,
                    "on_time": 0,
                    "late": 0,
                }
            ),
        },
    )

    with TestClient(_create_test_app(pool, None)) as client:
        response = client.get("/api/punctuality/daily?date=2026-10-18")

    assert response.status_code == 200
    assert response.json()["most_punctual"] == []
    assert response.json()["least_punctual"] == []
    assert response.json()["totals"]["samples"] == 0


def test_daily_punctuality_validates_date_limit_and_min_samples_before_querying() -> None:
    pool = FakeReadPool([])
    invalid_queries = [
        {"date": "2026-02-30"},
        {"date": "2026-10-18", "limit": "0"},
        {"date": "2026-10-18", "min_samples": "0"},
        {"date": "2026-10-18", "min_samples": "1000001"},
    ]

    with TestClient(_create_test_app(pool, None)) as client:
        responses = [
            client.get("/api/punctuality/daily", params=params)
            for params in invalid_queries
        ]

    assert [response.status_code for response in responses] == [422] * len(
        invalid_queries
    )
    assert pool.daily_calls == []


def test_routes_returns_504_when_database_query_exceeds_short_timeout(
    monkeypatch,
) -> None:
    class SlowPool(FakeReadPool):
        async def fetch(
            self, query: str, *arguments: object
        ) -> Sequence[dict[str, Any]]:
            await asyncio.sleep(0.05)
            return []

    monkeypatch.setattr(api_routes, "API_QUERY_TIMEOUT_SECONDS", 0.005)
    pool = SlowPool([])

    with TestClient(_create_test_app(pool, None)) as client:
        response = client.get("/api/routes")

    assert response.status_code == 504
    assert response.json()["detail"] == "Transit data query timed out"
