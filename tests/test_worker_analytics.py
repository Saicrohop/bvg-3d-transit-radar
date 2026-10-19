import asyncio
from datetime import date, datetime, timezone

from bvg_radar.realtime.analytics import RouteObservationRow
from bvg_radar.realtime.contracts import EstimatedVehiclePosition
from bvg_radar.realtime.models import (
    GtfsRealtimeFetchResult,
    GtfsRealtimeFetchStatus,
    GtfsRealtimeSnapshot,
    TripScheduleRelationship,
    TripUpdate,
)
from bvg_radar.realtime.worker import TripUpdateIngestionWorker

OBSERVED_AT = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def trip_update(trip_id: str) -> TripUpdate:
    return TripUpdate(
        entity_id=f"entity-{trip_id}",
        trip_id=trip_id,
        route_id="route-7",
        service_date=date(2026, 10, 18),
        trip_update_timestamp=1_792_337_280,
        stop_time_updates=(),
        schedule_relationship=TripScheduleRelationship.SCHEDULED,
    )


def position(trip_id: str, delay: int | None) -> EstimatedVehiclePosition:
    return EstimatedVehiclePosition(
        entity_id=f"entity-{trip_id}",
        trip_id=trip_id,
        route_id="route-7",
        shape_id="shape-1",
        previous_stop_id="stop-1",
        next_stop_id="stop-2",
        delay_seconds=delay,
        estimated_next_arrival=datetime(2026, 10, 18, 12, 5, tzinfo=timezone.utc),
        longitude=13.4,
        latitude=52.5,
        bearing_degrees=90.0,
        speed_mps=8.0,
        observed_at=OBSERVED_AT,
        timing_source="schedule_only" if delay is None else "realtime_delay",
        feed_timestamp=None,
        trip_update_timestamp=None,
        service_date=date(2026, 10, 18),
        is_estimated=True,
        position_status="estimated_from_trip_update",
        vehicle_category="bus",
    )


class Source:
    async def fetch(self) -> GtfsRealtimeFetchResult:
        return GtfsRealtimeFetchResult(
            status=GtfsRealtimeFetchStatus.UPDATED,
            snapshot=GtfsRealtimeSnapshot(
                feed_timestamp=1_792_337_280,
                trip_updates=(trip_update("a"), trip_update("b"), trip_update("c")),
                deleted_entities=(),
            ),
        )


class Estimator:
    async def estimate_many(self, _updates, _observed_at, max_positions=None):
        return (position("a", 60), position("b", 61), position("c", None))


class Publisher:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.payload = None

    async def publish(self, event: dict[str, object]) -> None:
        self.events.append("publish")
        self.payload = event


class Recorder:
    def __init__(self, events: list[str], failure: Exception | None = None) -> None:
        self.events = events
        self.failure = failure
        self.recorded = None

    async def record_cycle(
        self,
        cycle_id: str,
        observed_at: datetime,
        rows: tuple[RouteObservationRow, ...],
    ) -> bool:
        self.events.append("analytics")
        self.recorded = cycle_id, observed_at, rows
        if self.failure is not None:
            raise self.failure
        return True


def test_worker_records_analytics_after_snapshot_publish_without_changing_contract() -> None:
    events: list[str] = []
    publisher = Publisher(events)
    recorder = Recorder(events)
    worker = TripUpdateIngestionWorker(
        Source(), Estimator(), publisher, analytics_recorder=recorder
    )

    result = asyncio.run(worker.run_once(OBSERVED_AT))

    assert events == ["publish", "analytics"]
    assert result.estimated_positions_published == 3
    assert publisher.payload["schema_version"] == 1
    assert len(publisher.payload["positions"]) == 3
    cycle_id, observed_at, rows = recorder.recorded
    assert cycle_id == publisher.payload["cycle_id"]
    assert observed_at == OBSERVED_AT
    assert rows == (
        {
            "route_id": "route-7",
            "vehicle_category": "bus",
            "samples": 2,
            "on_time": 1,
            "late": 1,
            "sum_delay_seconds": 121,
        },
    )


def test_analytics_failure_does_not_suppress_an_already_published_snapshot(caplog) -> None:
    events: list[str] = []
    publisher = Publisher(events)
    recorder = Recorder(events, RuntimeError("analytics database unavailable"))
    worker = TripUpdateIngestionWorker(
        Source(), Estimator(), publisher, analytics_recorder=recorder
    )

    result = asyncio.run(worker.run_once(OBSERVED_AT))

    assert result.position_snapshots_published == 1
    assert publisher.payload["type"] == "vehicle_position_snapshot"
    assert events == ["publish", "analytics"]
    assert "route punctuality analytics write failed" in caplog.text
