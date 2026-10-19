import asyncio
from datetime import UTC, datetime

import pytest
from test_trip_update_worker import (
    MatchingEstimator,
    NotModifiedSource,
    RecordingPublisher,
)

from bvg_radar.realtime.runner import DryRunConfig
from bvg_radar.realtime.worker import TripUpdateIngestionWorker
from bvg_radar.server import RealtimeServerSettings


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), float("-inf"), 0.0, -1.0, True, "1", None]
)
@pytest.mark.parametrize(
    "field",
    ["poll_interval_seconds", "request_timeout_seconds", "send_timeout_seconds"],
)
def test_server_rejects_nonfinite_or_nonpositive_temporal_settings(field, value):
    with pytest.raises(ValueError, match=field):
        RealtimeServerSettings(database_url="postgresql://local.test", **{field: value})


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), float("-inf"), 0.0, -1.0, True, "1", None]
)
def test_runner_rejects_nonfinite_or_nonpositive_request_timeout(value):
    with pytest.raises(ValueError, match="request_timeout_seconds"):
        DryRunConfig(
            database_url="postgresql://local.test", request_timeout_seconds=value
        )


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), float("-inf"), 0.0, -1.0, True, "1", None]
)
def test_worker_rejects_invalid_cadence_even_when_already_stopped(value):
    async def run():
        stop = asyncio.Event()
        stop.set()
        worker = TripUpdateIngestionWorker(
            NotModifiedSource(), MatchingEstimator(), RecordingPublisher([])
        )
        with pytest.raises(ValueError, match="interval_seconds"):
            await worker.run_forever(value, stop, lambda: datetime.now(UTC))

    asyncio.run(run())


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, 1.5, 0, -1])
def test_server_requires_positive_integer_database_pool_size(value):
    with pytest.raises(ValueError, match="database_pool_size"):
        RealtimeServerSettings(
            database_url="postgresql://local.test", database_pool_size=value
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, 1.5, 0, -1])
def test_runner_requires_positive_integer_position_limit(value):
    with pytest.raises(ValueError, match="max_positions"):
        DryRunConfig(database_url="postgresql://local.test", max_positions=value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, 1.5, 0, -1])
def test_worker_requires_positive_integer_position_limit_before_fetch(value):
    worker = TripUpdateIngestionWorker(
        NotModifiedSource(), MatchingEstimator(), RecordingPublisher([])
    )
    with pytest.raises(ValueError, match="max_positions"):
        asyncio.run(worker.run_once(datetime.now(UTC), max_positions=value))
