import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from bvg_radar.realtime.analytics import AsyncpgRouteAnalyticsRecorder


class RecordingConnection:
    def __init__(self) -> None:
        self.query = None
        self.arguments = None

    async def fetchval(self, query, *arguments):
        self.query = query
        self.arguments = arguments
        return True


class RecordingPool:
    def __init__(self, connection: RecordingConnection) -> None:
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


def test_asyncpg_recorder_uses_bound_parameters_and_json_payload() -> None:
    connection = RecordingConnection()
    recorder = AsyncpgRouteAnalyticsRecorder(RecordingPool(connection))
    cycle_id = "36ef22c3-1f2f-4d61-a822-74871f784b82"
    observed_at = datetime(2026, 10, 18, 12, 15, tzinfo=timezone.utc)
    rows = (
        {
            "route_id": "bus-100",
            "vehicle_category": "bus",
            "samples": 1,
            "on_time": 0,
            "late": 1,
            "sum_delay_seconds": 61,
        },
    )

    inserted = asyncio.run(recorder.record_cycle(cycle_id, observed_at, rows))

    assert inserted is True
    assert "analytics.record_route_observations" in connection.query
    assert connection.arguments[0] == cycle_id
    assert connection.arguments[1] == observed_at
    assert json.loads(connection.arguments[2]) == list(rows)
