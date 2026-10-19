import asyncio
import json
from io import StringIO

from bvg_radar.realtime import runner
from bvg_radar.realtime.runner import JsonLinePositionEventPublisher


def test_json_line_publisher_writes_a_websocket_ready_snapshot() -> None:
    output = StringIO()
    publisher = JsonLinePositionEventPublisher(output)
    event = {
        "type": "vehicle_position_snapshot",
        "schema_version": 1,
        "cycle_id": "cycle-42",
        "feed_timestamp": None,
        "observed_at": "2026-07-19T10:40:00Z",
        "positions": [],
        "statistics": {
            "trip_updates_received": 0,
            "positions_estimated": 0,
            "positions_suppressed": 0,
        },
    }

    asyncio.run(publisher.publish(event))

    assert json.loads(output.getvalue()) == event


def test_build_worker_injects_the_batch_estimator_from_the_shared_connection(
    monkeypatch,
) -> None:
    source = object()
    estimator = object()
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
    assert "route_metadata_lookup" not in dependencies
    assert dependencies["publisher"] is publisher
