import asyncio

import pytest
from fastapi.testclient import TestClient

from bvg_radar import server
from bvg_radar.realtime.websocket import (
    PositionWebSocketHub,
    SnapshotReplayError,
)
from bvg_radar.server import (
    RealtimeServerSettings,
    create_app,
    create_transport_app,
)


def test_positions_endpoint_accepts_a_websocket_connection() -> None:
    app = create_transport_app(PositionWebSocketHub())

    with TestClient(app) as client:
        with client.websocket_connect("/ws/positions") as websocket:
            assert websocket is not None


def test_positions_endpoint_replays_the_latest_snapshot() -> None:
    hub = PositionWebSocketHub()
    app = create_transport_app(hub)
    snapshot = {
        "type": "vehicle_position_snapshot",
        "schema_version": 1,
        "cycle_id": "cycle-retained",
        "feed_timestamp": None,
        "observed_at": "2026-07-19T10:40:00Z",
        "positions": [],
        "statistics": {
            "trip_updates_received": 0,
            "positions_estimated": 0,
            "positions_suppressed": 0,
        },
    }

    with TestClient(app) as client:
        client.portal.call(hub.publish, snapshot)
        with client.websocket_connect("/ws/positions") as websocket:
            assert websocket.receive_json() == snapshot


class EvictedWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.receive_started = asyncio.Event()
        self.receive_cancelled = False
        self.close_codes: list[int] = []

    async def accept(self) -> None:
        self.accepted = True

    async def receive(self) -> dict[str, object]:
        self.receive_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.receive_cancelled = True
            raise
        raise AssertionError("unreachable")

    async def close(self, code: int = 1000) -> None:
        self.close_codes.append(code)


class EvictingHub:
    def __init__(self) -> None:
        self.disconnect_calls = 0

    async def connect(self, websocket: EvictedWebSocket) -> None:
        await websocket.accept()

    async def wait_until_disconnected(self, websocket: EvictedWebSocket) -> None:
        await websocket.receive_started.wait()

    async def disconnect(self, _websocket: EvictedWebSocket) -> None:
        self.disconnect_calls += 1


async def serve_until_hub_evicts_client() -> tuple[EvictedWebSocket, EvictingHub]:
    websocket = EvictedWebSocket()
    hub = EvictingHub()

    await server._serve_position_websocket(websocket, hub)

    return websocket, hub


def test_positions_endpoint_terminates_an_evicted_client_cleanly() -> None:
    websocket, hub = asyncio.run(serve_until_hub_evicts_client())

    assert websocket.accepted is True
    assert websocket.receive_cancelled is True
    assert websocket.close_codes == [1011]
    assert hub.disconnect_calls == 1


class ReplayFailingHub(EvictingHub):
    async def connect(self, websocket: EvictedWebSocket) -> None:
        await websocket.accept()
        raise SnapshotReplayError("retained snapshot replay failed")


async def serve_after_retained_replay_fails() -> EvictedWebSocket:
    websocket = EvictedWebSocket()

    await server._serve_position_websocket(websocket, ReplayFailingHub())

    return websocket


def test_positions_endpoint_closes_when_retained_replay_fails() -> None:
    websocket = asyncio.run(serve_after_retained_replay_fails())

    assert websocket.accepted is True
    assert websocket.close_codes == [1011]


def test_server_settings_are_loaded_from_non_versioned_environment_values() -> None:
    settings = RealtimeServerSettings.from_environment(
        {
            "BVG_DATABASE_URL": "postgresql://local-test",
            "BVG_WS_POLL_INTERVAL_SECONDS": "5",
            "BVG_WS_REQUEST_TIMEOUT_SECONDS": "10",
            "BVG_WS_SEND_TIMEOUT_SECONDS": "0.25",
            "BVG_WS_DB_POOL_SIZE": "4",
        }
    )

    assert settings.database_url == "postgresql://local-test"
    assert settings.poll_interval_seconds == 5.0
    assert settings.request_timeout_seconds == 10.0
    assert settings.send_timeout_seconds == 0.25
    assert settings.database_pool_size == 4


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("inf"), float("nan")])
def test_server_settings_reject_an_invalid_send_timeout(timeout: float) -> None:
    with pytest.raises(ValueError, match="send_timeout_seconds"):
        RealtimeServerSettings(
            database_url="postgresql://local-test",
            send_timeout_seconds=timeout,
        )


def test_create_app_supplies_the_configured_send_timeout_to_the_hub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, float] = {}

    class CapturingHub(PositionWebSocketHub):
        def __init__(self, send_timeout_seconds: float) -> None:
            captured["send_timeout_seconds"] = send_timeout_seconds
            super().__init__(send_timeout_seconds)

    monkeypatch.setattr(server, "PositionWebSocketHub", CapturingHub)

    create_app(
        RealtimeServerSettings(
            database_url="postgresql://local-test",
            send_timeout_seconds=0.125,
        )
    )

    assert captured == {"send_timeout_seconds": 0.125}


def test_full_server_app_exposes_the_positions_endpoint_before_lifespan_startup() -> (
    None
):
    app = create_app(RealtimeServerSettings(database_url="postgresql://local-test"))

    assert any(route.path == "/ws/positions" for route in app.routes)
    assert "/api/routes" in app.openapi()["paths"]


def test_local_api_cors_allows_the_configured_vite_origin() -> None:
    app = create_app(RealtimeServerSettings(database_url="postgresql://local-test"))
    client = TestClient(app)

    response = client.options(
        "/api/routes",
        headers={
            "Origin": "http://127.0.0.1:5175",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5175"
    assert "GET" in response.headers["access-control-allow-methods"]


def test_local_api_cors_rejects_unconfigured_origins() -> None:
    app = create_app(RealtimeServerSettings(database_url="postgresql://local-test"))
    client = TestClient(app)

    response = client.options(
        "/api/routes",
        headers={
            "Origin": "https://unapproved.invalid",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_server_lifespan_injects_batch_estimator_from_the_shared_pool(
    monkeypatch,
) -> None:
    session = object()
    pool = FakePool()
    source = object()
    estimator = object()
    dependencies: dict[str, object] = {}

    class FakeClientSession:
        def __init__(self, **_arguments: object) -> None:
            pass

        async def __aenter__(self) -> object:
            return session

        async def __aexit__(self, *_arguments: object) -> None:
            return None

    async def create_pool(**_arguments: object) -> FakePool:
        return pool

    class FakeWorker:
        async def run_forever(self, **_arguments: object) -> None:
            await server.asyncio.Event().wait()

    def capture_worker(**arguments: object) -> FakeWorker:
        dependencies.update(arguments)
        return FakeWorker()

    monkeypatch.setattr(server.aiohttp, "ClientSession", FakeClientSession)
    monkeypatch.setattr(server.asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(
        server,
        "AiohttpGtfsRealtimeSource",
        lambda *_arguments: source,
    )
    monkeypatch.setattr(
        server,
        "PostgisTripPositionEstimator",
        lambda _pool: estimator,
    )
    monkeypatch.setattr(server, "TripUpdateIngestionWorker", capture_worker)

    app = server.create_app(
        RealtimeServerSettings(database_url="postgresql://local-test")
    )
    with TestClient(app):
        assert app.state.database_pool is pool

    assert app.state.database_pool is None
    assert dependencies["source"] is source
    assert dependencies["estimator"] is estimator
    assert dependencies["analytics_recorder"]._pool is pool
    assert "route_metadata_lookup" not in dependencies
    assert pool.closed is True


class FakePool:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True
