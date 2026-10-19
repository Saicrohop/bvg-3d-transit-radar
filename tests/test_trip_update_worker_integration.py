import asyncio
import json
from datetime import date, datetime, timezone

import pytest

from bvg_radar.realtime.contracts import EstimatedVehiclePosition
from bvg_radar.realtime.models import (
    GtfsRealtimeFetchResult,
    GtfsRealtimeFetchStatus,
    GtfsRealtimeSnapshot,
    TripUpdate,
)
from bvg_radar.realtime.postgis import PostgisTripPositionEstimator
from bvg_radar.realtime.worker import (
    AsyncQueuePositionEventPublisher,
    TripUpdateIngestionWorker,
)


class MockGtfsRealtimeDownload:
    def __init__(self, update: TripUpdate) -> None:
        self._update = update
        self.calls = 0

    async def fetch(self) -> GtfsRealtimeFetchResult:
        self.calls += 1
        return GtfsRealtimeFetchResult(
            status=GtfsRealtimeFetchStatus.UPDATED,
            snapshot=GtfsRealtimeSnapshot(
                feed_timestamp=1_784_543_900,
                trip_updates=(self._update,),
            ),
        )


class MockAsyncpgPool:
    def __init__(self) -> None:
        self.arguments: tuple[object, ...] | None = None
        self.query: str | None = None
        self.calls = 0

    async def fetch(self, query: str, *arguments: object) -> list[dict[str, object]]:
        self.calls += 1
        self.query = query
        self.arguments = arguments
        return [
            {
                "input_index": 0,
                "trip_id": "trip-s41",
                "route_id": "route-s41",
                "shape_id": "shape-s41",
                "previous_stop_id": "alexanderplatz",
                "next_stop_id": "hackescher-markt",
                "delay_seconds": 0,
                "timing_source": "realtime_delay",
                "estimated_next_arrival": datetime(
                    2026, 7, 20, 10, 5, tzinfo=timezone.utc
                ),
                "longitude": 13.405,
                "latitude": 52.52,
                "bearing_degrees": 90.0,
                "speed_mps": 10.5,
                "is_estimated": True,
                "position_status": "estimated_from_trip_update",
                "route_type": 2,
                "route_short_name": "S41",
            }
        ]


def test_worker_enriches_s41_and_publishes_its_category_in_snapshot_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = TripUpdate(
        entity_id="entity-s41",
        trip_id="trip-s41",
        route_id="route-s41",
        service_date=date(2026, 7, 20),
        trip_update_timestamp=1_784_544_000,
        stop_time_updates=(),
    )
    source = MockGtfsRealtimeDownload(update)
    database = MockAsyncpgPool()
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    serialized_positions: list[EstimatedVehiclePosition] = []
    original_serializer = EstimatedVehiclePosition.to_websocket_event

    def capture_serializer(
        position: EstimatedVehiclePosition,
    ) -> dict[str, object]:
        serialized_positions.append(position)
        return original_serializer(position)

    monkeypatch.setattr(
        EstimatedVehiclePosition,
        "to_websocket_event",
        capture_serializer,
    )
    worker = TripUpdateIngestionWorker(
        source=source,
        estimator=PostgisTripPositionEstimator(database, batch_size=32),
        publisher=AsyncQueuePositionEventPublisher(queue),
    )

    result = asyncio.run(
        worker.run_once(observed_at=datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc))
    )

    assert result.estimated_positions_published == 1
    assert source.calls == 1
    assert database.calls == 1
    assert database.query is not None
    assert "estimate_trip_positions_batch" in database.query
    assert database.arguments is not None
    assert database.arguments[0] == datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)
    assert json.loads(str(database.arguments[1])) == [
        {
            "service_date": "2026-07-20",
            "stop_time_updates": [],
            "trip_id": "trip-s41",
        }
    ]
    assert len(serialized_positions) == 1
    assert serialized_positions[0].vehicle_category == "s_bahn"
    assert serialized_positions[0].route_short_name == "S41"
    assert serialized_positions[0].feed_timestamp == datetime.fromtimestamp(
        1_784_543_900, timezone.utc
    )
    snapshot = queue.get_nowait()
    assert snapshot["type"] == "vehicle_position_snapshot"
    assert snapshot["schema_version"] == 1
    assert snapshot["statistics"] == {
        "trip_updates_received": 1,
        "positions_estimated": 1,
        "positions_suppressed": 0,
    }
    positions = snapshot["positions"]
    assert isinstance(positions, list) and len(positions) == 1
    event = positions[0]
    assert event["vehicle_category"] == "s_bahn"
    assert event["route_short_name"] == "S41"
    assert event["timing_source"] == "realtime_delay"
    assert event["delay_seconds"] == 0
    assert event["service_date"] == "2026-07-20"
