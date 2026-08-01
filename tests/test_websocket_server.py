from fastapi.testclient import TestClient

from bvg_radar import server
from bvg_radar.realtime.websocket import PositionWebSocketHub
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


def test_server_settings_are_loaded_from_non_versioned_environment_values() -> None:
    settings = RealtimeServerSettings.from_environment(
        {
            "BVG_DATABASE_URL": "postgresql://local-test",
            "BVG_WS_POLL_INTERVAL_SECONDS": "5",
            "BVG_WS_REQUEST_TIMEOUT_SECONDS": "10",
            "BVG_WS_DB_POOL_SIZE": "4",
        }
    )

    assert settings.database_url == "postgresql://local-test"
    assert settings.poll_interval_seconds == 5.0
    assert settings.request_timeout_seconds == 10.0
    assert settings.database_pool_size == 4


def test_full_server_app_exposes_the_positions_endpoint_before_lifespan_startup() -> None:
    app = create_app(RealtimeServerSettings(database_url="postgresql://local-test"))

    assert any(route.path == "/ws/positions" for route in app.routes)


def test_server_lifespan_injects_route_lookup_from_the_shared_pool(
    monkeypatch,
) -> None:
    session = object()
    pool = FakePool()
    source = object()
    estimator = object()
    route_lookup = object()
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
    monkeypatch.setattr(
        server,
        "GtfsRouteMetadataLookup",
        lambda _pool: route_lookup,
        raising=False,
    )
    monkeypatch.setattr(server, "TripUpdateIngestionWorker", capture_worker)

    app = server.create_app(
        RealtimeServerSettings(database_url="postgresql://local-test")
    )
    with TestClient(app):
        pass

    assert dependencies["source"] is source
    assert dependencies["estimator"] is estimator
    assert dependencies.get("route_metadata_lookup") is route_lookup
    assert pool.closed is True


class FakePool:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True
