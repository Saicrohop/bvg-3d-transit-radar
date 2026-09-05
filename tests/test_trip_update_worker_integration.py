import asyncio
from datetime import date, datetime, timezone

import pytest

from bvg_radar.realtime.contracts import EstimatedVehiclePosition
from bvg_radar.realtime.gtfs_route_metadata import GtfsRouteMetadataLookup
from bvg_radar.realtime.models import (
    GtfsRealtimeFetchResult,
    GtfsRealtimeFetchStatus,
    GtfsRealtimeSnapshot,
    TripUpdate,
)
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


class MockPostgisEstimator:
    async def estimate(
        self, update: TripUpdate, observed_at: datetime
    ) -> EstimatedVehiclePosition:
        return EstimatedVehiclePosition(
            entity_id=update.entity_id,
            trip_id=update.trip_id,
            route_id=update.route_id,
            shape_id="shape-s41",
            previous_stop_id="alexanderplatz",
            next_stop_id="hackescher-markt",
            delay_seconds=0,
            estimated_next_arrival=datetime(
                2026, 7, 20, 10, 5, tzinfo=timezone.utc
            ),
            longitude=13.405,
            latitude=52.52,
            bearing_degrees=90.0,
            speed_mps=10.5,
            observed_at=observed_at,
        )


class MockAsyncpgPool:
    def __init__(self) -> None:
        self.arguments: tuple[object, ...] | None = None

    async def fetchrow(self, _query: str, *arguments: object) -> dict[str, object]:
        self.arguments = arguments
        return {
            "route_type": 2,
            "route_short_name": "S41",
        }


def test_worker_enriches_s41_and_publishes_its_category_in_websocket_json(
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
        estimator=MockPostgisEstimator(),
        route_metadata_lookup=GtfsRouteMetadataLookup(database),
        publisher=AsyncQueuePositionEventPublisher(queue),
    )

    result = asyncio.run(
        worker.run_once(
            observed_at=datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)
        )
    )

    assert result.estimated_positions_published == 1
    assert source.calls == 1
    assert database.arguments == ("trip-s41",)
    assert len(serialized_positions) == 1
    assert serialized_positions[0].vehicle_category == "s_bahn"
    assert serialized_positions[0].route_short_name == "S41"
    event = queue.get_nowait()
    assert event["vehicle_category"] == "s_bahn"
    assert event["route_short_name"] == "S41"
