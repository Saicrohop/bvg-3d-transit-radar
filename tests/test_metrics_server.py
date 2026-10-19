"""ASGI-only tests; no browser, live psutil sampling or user SQLite reads."""

import inspect
from concurrent.futures import ThreadPoolExecutor
from threading import Event, get_ident
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from bvg_radar import hermes_metrics
from bvg_radar import metrics_server as server


@pytest.fixture(autouse=True)
def forbid_real_data(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No user data or real CPU sampling in API tests")

    monkeypatch.setattr(hermes_metrics, "_connect", forbidden)
    monkeypatch.setattr(hermes_metrics, "_cron_jobs_path", forbidden)
    for name in ["build_snapshot", "query_cron_jobs", "query_today_stats",
                 "query_daily_usage", "query_daily_usage_by_provider", "query_session_usage"]:
        monkeypatch.setattr(server, name, forbidden)
    monkeypatch.setattr(server.psutil, "cpu_percent", forbidden)


@pytest.mark.parametrize("path", [
    "/", "/api/metrics", "/api/system", "/api/activity", "/api/cron",
    "/api/stats/today", "/api/usage/daily", "/api/usage/providers", "/api/usage/sessions",
])
def test_blocking_routes_are_sync_for_fastapi_threadpool(path):
    route = next(route for route in server.app.routes if route.path == path)
    assert not inspect.iscoroutinefunction(route.endpoint)


def test_cpu_sample_does_not_block_health_on_same_event_loop(monkeypatch):
    started = Event()
    release = Event()
    worker_threads = []

    def cpu_percent(interval):
        worker_threads.append(get_ident())
        started.set()
        assert release.wait(timeout=5), "Health request failed to release CPU sample"
        return 12.0

    monkeypatch.setattr(server.psutil, "cpu_percent", cpu_percent)
    monkeypatch.setattr(server.psutil, "virtual_memory", lambda: SimpleNamespace(used=0, total=0, percent=0))
    monkeypatch.setattr(server.psutil, "disk_usage", lambda _: SimpleNamespace(used=0, total=0, percent=0))
    monkeypatch.setattr(server.psutil, "cpu_count", lambda: 4)
    with TestClient(server.app, base_url="http://127.0.0.1:8001") as client:
        loop_thread = client.portal.call(get_ident)
        with ThreadPoolExecutor(max_workers=2) as pool:
            system = pool.submit(client.get, "/api/system")
            try:
                assert started.wait(timeout=2)
                assert worker_threads != [loop_thread]
                health = pool.submit(client.get, "/api/health")
                assert health.result(timeout=2).json()["status"] == "ok"
            finally:
                release.set()
            assert system.result(timeout=2).json()["cpu_percent"] == 12.0


@pytest.mark.parametrize("origin", [
    "http://127.0.0.1:8001", "http://localhost:8001", "http://[::1]:8001",
])
def test_cors_allows_only_explicit_loopback_origins(origin):
    with TestClient(server.app, base_url="http://127.0.0.1:8001") as client:
        response = client.options("/api/health", headers={
            "Origin": origin, "Access-Control-Request-Method": "GET",
        })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-methods"] == "GET"
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.parametrize("origin", [
    "https://evil.example", "null", "http://localhost:9000",
    "http://127.0.0.1.evil.example:8001", "http://localhost.evil.example:8001",
])
def test_cors_denies_other_origins(origin):
    with TestClient(server.app, base_url="http://127.0.0.1:8001") as client:
        response = client.options("/api/health", headers={
            "Origin": origin, "Access-Control-Request-Method": "GET",
        })
    assert response.status_code in (400, 403)
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("headers", [
    {"Host": "evil.example"},
    {"Origin": "https://evil.example"},
    {"Sec-Fetch-Site": "cross-site"},
])
def test_telemetry_rejects_untrusted_host_or_browser_origin(headers):
    with TestClient(server.app, base_url="http://127.0.0.1:8001") as client:
        response = client.get("/api/health", headers=headers)
    assert response.status_code in (400, 403)


def test_cors_does_not_allow_write_methods():
    with TestClient(server.app, base_url="http://127.0.0.1:8001") as client:
        response = client.options("/api/health", headers={
            "Origin": "http://localhost:8001", "Access-Control-Request-Method": "POST",
        })
    assert response.status_code == 400
