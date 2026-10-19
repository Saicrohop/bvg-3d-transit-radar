import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from test_gtfs_realtime_source import (
    FakeResponse,
    FakeSession,
    protobuf_empty_feed,
    protobuf_trip_update,
)
from test_trip_update_worker import MatchingEstimator

from bvg_radar.realtime.source import AiohttpGtfsRealtimeSource
from bvg_radar.realtime.worker import (
    TripUpdateIngestionWorker,
    _position_snapshot_cycle_id,
)


@pytest.mark.parametrize("failure_port", ["estimator", "publisher"])
def test_worker_retries_pending_snapshot_without_refreshing_original_provenance(
    failure_port,
):
    async def scenario():
        session = FakeSession(
            [
                FakeResponse(200, protobuf_trip_update(), etag='"first"'),
                FakeResponse(304),
                FakeResponse(200, protobuf_empty_feed(), etag='"second"'),
                FakeResponse(304),
            ]
        )
        source = AiohttpGtfsRealtimeSource(session, "https://example.test/feed")
        observed_times = []
        estimator_calls = 0
        publisher_calls = 0
        attempts = []
        published = []

        class Estimator(MatchingEstimator):
            async def estimate_many(self, updates, observed_at, max_positions=None):
                nonlocal estimator_calls
                estimator_calls += 1
                observed_times.append(observed_at)
                if failure_port == "estimator" and estimator_calls <= 2:
                    raise RuntimeError("transient estimator failure")
                return await super().estimate_many(updates, observed_at, max_positions)

        class Publisher:
            async def publish(self, event):
                nonlocal publisher_calls
                publisher_calls += 1
                attempts.append(event)
                if failure_port == "publisher" and publisher_calls <= 2:
                    raise RuntimeError("transient publisher failure")
                published.append(event)

        worker = TripUpdateIngestionWorker(source, Estimator(), Publisher())
        original = datetime(2026, 7, 19, 10, tzinfo=UTC)
        for offset in range(2):
            with pytest.raises(RuntimeError, match="transient"):
                await worker.run_once(original + timedelta(seconds=offset * 15))
        recovered = await worker.run_once(original + timedelta(seconds=30))
        assert recovered.position_snapshots_published == 1
        assert (
            len(session.calls) == 1
        )  # retry the one retained snapshot before polling again
        assert observed_times == [original] * 3
        envelope = published[0]
        assert envelope["observed_at"] == "2026-07-19T10:00:00Z"
        assert envelope["positions"][0]["observed_at"] == envelope["observed_at"]
        assert envelope["cycle_id"] == _position_snapshot_cycle_id(
            1_784_457_600, original
        )
        if failure_port == "publisher":
            assert attempts == [envelope] * 3

        not_modified = await worker.run_once(original + timedelta(seconds=45))
        assert not_modified.position_snapshots_published == 0
        assert len(published) == 1
        assert session.calls[1][1]["If-None-Match"] == '"first"'
        next_cycle = await worker.run_once(original + timedelta(seconds=60))
        assert next_cycle.position_snapshots_published == 1
        assert published[1]["positions"] == []
        assert published[1]["observed_at"] == "2026-07-19T10:01:00Z"
        await worker.run_once(original + timedelta(seconds=75))
        assert len(published) == 2
        assert session.calls[-1][1]["If-None-Match"] == '"second"'

    asyncio.run(scenario())
