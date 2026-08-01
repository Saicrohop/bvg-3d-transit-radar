import asyncio
import json
from io import StringIO

from bvg_radar.realtime import runner
from bvg_radar.realtime.runner import JsonLinePositionEventPublisher


def test_json_line_publisher_writes_a_websocket_ready_event() -> None:
    output = StringIO()
    publisher = JsonLinePositionEventPublisher(output)
    event = {
        "type": "vehicle_position",
        "source": "trip_update_interpolation",
        "is_estimated": True,
        "trip_id": "trip-42",
        "longitude": 13.4,
    }

    asyncio.run(publisher.publish(event))

    assert json.loads(output.getvalue()) == event


def test_build_worker_injects_route_lookup_from_the_shared_connection(
    monkeypatch,
) -> None:
    source = object()
    estimator = object()
    route_lookup = object()
    publisher = JsonLinePositionEventPublisher(StringIO())
    dependencies: dict[str, object] = {}

    monkeypatch.setattr(
        runner,
        "AiohttpGtfsRealtimeSource",
        lambda **_arguments: source,
    )
    monkeypatch.setattr(
        runner,
        "PostgisTripPositionEstimator",
        lambda **_arguments: estimator,
    )
    monkeypatch.setattr(
        runner,
        "GtfsRouteMetadataLookup",
        lambda connection: route_lookup,
        raising=False,
    )

    def capture_worker(**arguments: object) -> object:
        dependencies.update(arguments)
        return object()

    monkeypatch.setattr(runner, "TripUpdateIngestionWorker", capture_worker)

    worker = runner.build_worker(
        session=object(),
        connection=object(),
        publisher=publisher,
        feed_url="https://example.invalid/feed",
    )

    assert worker is not None
    assert dependencies["source"] is source
    assert dependencies["estimator"] is estimator
    assert dependencies.get("route_metadata_lookup") is route_lookup
    assert dependencies["publisher"] is publisher
