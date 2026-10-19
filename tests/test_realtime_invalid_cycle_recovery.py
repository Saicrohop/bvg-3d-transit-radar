import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest
from google.transit import gtfs_realtime_pb2
from test_gtfs_realtime_source import (
    FakeResponse,
    FakeSession,
    protobuf_empty_feed,
    protobuf_trip_update,
)
from test_trip_update_worker import MatchingEstimator

from bvg_radar.realtime import source as source_module
from bvg_radar.realtime.models import GtfsRealtimeFetchResult, GtfsRealtimeFetchStatus, StopTimeUpdate
from bvg_radar.realtime.normalization import (
    InvalidGtfsRealtimeTimestamp,
    snapshot_from_feed,
)
from bvg_radar.realtime.source import (
    AiohttpGtfsRealtimeSource,
    GtfsRealtimeFetchError,
)
from bvg_radar.realtime.worker import InvalidIngestionCycleError, TripUpdateIngestionWorker


class RecordingPublisher:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


class SequenceSource:
    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.calls = 0

    async def fetch(self):
        self.calls += 1
        return GtfsRealtimeFetchResult(
            GtfsRealtimeFetchStatus.UPDATED, self.snapshots.pop(0)
        )


def empty_snapshot():
    return snapshot_from_feed(
        gtfs_realtime_pb2.FeedMessage.FromString(protobuf_empty_feed())
    )


def test_worker_recovers_from_unrepresentable_feed_timestamp_without_caching_it():
    async def scenario():
        feed = gtfs_realtime_pb2.FeedMessage.FromString(protobuf_empty_feed())
        feed.header.incrementality = gtfs_realtime_pb2.FeedHeader.FULL_DATASET
        feed.header.timestamp = 2**64 - 1
        assert feed.IsInitialized()
        session = FakeSession(
            [
                FakeResponse(200, feed.SerializeToString(), etag='"invalid"'),
                FakeResponse(200, protobuf_empty_feed(), etag='"valid"'),
            ]
        )
        source = AiohttpGtfsRealtimeSource(session, "https://example.test/feed")
        publisher = RecordingPublisher()
        worker = TripUpdateIngestionWorker(source, MatchingEstimator(), publisher)
        observed_at = datetime(2026, 7, 19, 10, tzinfo=UTC)

        with pytest.raises(GtfsRealtimeFetchError):
            await worker.run_once(observed_at)
        assert source._etag is None
        assert worker._pending_cycle is None
        assert publisher.events == []

        result = await worker.run_once(observed_at)
        assert len(session.calls) == 2
        assert "If-None-Match" not in session.calls[1][1]
        assert result.position_snapshots_published == 1
        assert len(publisher.events) == 1
        assert publisher.events[0]["positions"] == []
        assert source._etag == '"valid"'

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("field", "timestamp"),
    [
        ("feed", 253402300800),  # First second past datetime.max's year.
        ("trip_update", 2**64 - 1),
        ("trip_update", 253402300800),
        ("arrival", 2**63 - 1),
        ("arrival", -(2**63)),
        ("arrival", 253402300800),
        ("departure", 2**63 - 1),
        ("departure", -(2**63)),
        ("departure", 253402300800),
    ],
)
def test_source_rejects_unrepresentable_entity_timestamp_preserving_previous_etag(
    field, timestamp
):
    async def scenario():
        feed = gtfs_realtime_pb2.FeedMessage.FromString(protobuf_trip_update())
        update = feed.entity[0].trip_update
        if field == "feed":
            feed.header.timestamp = timestamp
        elif field == "trip_update":
            update.timestamp = timestamp
        else:
            stop = update.stop_time_update.add()
            stop.stop_sequence = 1
            getattr(stop, field).time = timestamp
        assert feed.IsInitialized()
        session = FakeSession(
            [
                FakeResponse(200, protobuf_empty_feed(), etag='"previous"'),
                FakeResponse(200, feed.SerializeToString(), etag='"invalid"'),
                FakeResponse(200, protobuf_empty_feed(), etag='"corrected"'),
            ]
        )
        source = AiohttpGtfsRealtimeSource(session, "https://example.test/feed")
        await source.fetch()
        with pytest.raises(GtfsRealtimeFetchError) as raised:
            await source.fetch()
        assert isinstance(raised.value.__cause__, InvalidGtfsRealtimeTimestamp)
        assert source._etag == '"previous"'
        assert (await source.fetch()).snapshot is not None
        assert session.calls[2][1]["If-None-Match"] == '"previous"'
        assert source._etag == '"corrected"'

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "observed_at",
    [
        datetime(2026, 7, 19),
        datetime.min.replace(tzinfo=timezone(timedelta(hours=14))),
        datetime.max.replace(tzinfo=timezone(timedelta(hours=-12))),
    ],
)
def test_worker_rejects_invalid_observed_at_before_fetch_or_pending_assignment(observed_at):
    async def scenario():
        source = SequenceSource([empty_snapshot()])
        publisher = RecordingPublisher()
        worker = TripUpdateIngestionWorker(source, MatchingEstimator(), publisher)
        with pytest.raises(InvalidIngestionCycleError, match="observed_at"):
            await worker.run_once(observed_at)
        assert source.calls == 0
        assert worker._pending_cycle is None
        result = await worker.run_once(datetime(2026, 7, 19, tzinfo=UTC))
        assert result.position_snapshots_published == 1
        assert source.calls == 1
        assert len(publisher.events) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("field", ["feed", "trip_update", "arrival", "departure"])
def test_worker_rejects_invalid_custom_source_timestamp_before_retaining_cycle(field):
    async def scenario():
        feed = gtfs_realtime_pb2.FeedMessage.FromString(protobuf_trip_update())
        stop = feed.entity[0].trip_update.stop_time_update.add()
        stop.stop_sequence = 1
        good = snapshot_from_feed(feed)
        if field == "feed":
            bad = replace(good, feed_timestamp=2**64 - 1)
        else:
            update = good.trip_updates[0]
            if field == "trip_update":
                update = replace(update, trip_update_timestamp=2**64 - 1)
            else:
                stop = replace(update.stop_time_updates[0], **{f"{field}_time": 2**63 - 1})
                update = replace(update, stop_time_updates=(stop,))
            bad = replace(good, trip_updates=(update,))
        source = SequenceSource([bad, empty_snapshot()])
        publisher = RecordingPublisher()
        worker = TripUpdateIngestionWorker(source, MatchingEstimator(), publisher)
        observed_at = datetime(2026, 7, 19, tzinfo=UTC)
        with pytest.raises(GtfsRealtimeFetchError):
            await worker.run_once(observed_at)
        assert worker._pending_cycle is None
        assert publisher.events == []
        result = await worker.run_once(observed_at)
        assert source.calls == 2
        assert result.position_snapshots_published == 1
        assert len(publisher.events) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("malformed", ["stop_sequence", "absolute_time"])
def test_worker_rejects_malformed_stop_fields_before_retaining_pending_cycle(malformed):
    async def scenario():
        good = snapshot_from_feed(
            gtfs_realtime_pb2.FeedMessage.FromString(protobuf_trip_update())
        )
        update = good.trip_updates[0]
        if malformed == "stop_sequence":
            bad_stop = StopTimeUpdate(
                stop_sequence=2**31,
                stop_id="stop-3",
                arrival_time=None,
                arrival_delay_seconds=None,
                departure_time=None,
                departure_delay_seconds=None,
            )
        else:
            bad_stop = StopTimeUpdate(
                stop_sequence=3,
                stop_id="stop-3",
                arrival_time=int(datetime(2099, 7, 19, tzinfo=UTC).timestamp()),
                arrival_delay_seconds=None,
                departure_time=None,
                departure_delay_seconds=None,
            )
        bad = replace(
            good,
            trip_updates=(replace(update, stop_time_updates=(bad_stop,)),),
        )
        source = SequenceSource([bad, empty_snapshot()])
        publisher = RecordingPublisher()
        worker = TripUpdateIngestionWorker(source, MatchingEstimator(), publisher)
        observed_at = datetime(2026, 7, 19, tzinfo=UTC)

        with pytest.raises(GtfsRealtimeFetchError):
            await worker.run_once(observed_at)
        assert worker._pending_cycle is None
        assert publisher.events == []

        result = await worker.run_once(observed_at)
        assert source.calls == 2
        assert result.position_snapshots_published == 1
        assert len(publisher.events) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("invalid_contract", ["provenance", "position_timestamp"])
def test_worker_discards_deterministic_position_contract_failure(invalid_contract):
    async def scenario():
        source = SequenceSource(
            [
                snapshot_from_feed(
                    gtfs_realtime_pb2.FeedMessage.FromString(protobuf_trip_update())
                ),
                empty_snapshot(),
            ]
        )
        publisher = RecordingPublisher()

        class InvalidContractEstimator(MatchingEstimator):
            async def estimate_many(self, updates, observed_at, max_positions=None):
                estimates = await super().estimate_many(updates, observed_at, max_positions)
                if invalid_contract == "provenance":
                    invalid = replace(
                        estimates[0], observed_at=observed_at - timedelta(seconds=1)
                    )
                else:
                    invalid = replace(
                        estimates[0], estimated_next_arrival=datetime(2026, 7, 19)
                    )
                return (invalid,)

        worker = TripUpdateIngestionWorker(source, InvalidContractEstimator(), publisher)
        observed_at = datetime(2026, 7, 19, tzinfo=UTC)
        with pytest.raises(InvalidIngestionCycleError):
            await worker.run_once(observed_at)
        assert worker._pending_cycle is None
        assert publisher.events == []
        recovered = await worker.run_once(observed_at + timedelta(seconds=15))
        assert source.calls == 2
        assert recovered.position_snapshots_published == 1
        assert len(publisher.events) == 1

    asyncio.run(scenario())


def test_source_does_not_classify_unexpected_normalizer_failure_as_invalid_input(monkeypatch):
    error = RuntimeError("unexpected normalization failure")

    def fail(_feed):
        raise error

    monkeypatch.setattr(source_module, "snapshot_from_feed", fail)
    source = AiohttpGtfsRealtimeSource(
        FakeSession([FakeResponse(200, protobuf_empty_feed(), etag='"uncommitted"')]),
        "https://example.test/feed",
    )
    with pytest.raises(RuntimeError) as raised:
        asyncio.run(source.fetch())
    assert raised.value is error
    assert source._etag is None


@pytest.mark.parametrize("failure_port", ["estimator", "publisher", "serializer"])
def test_value_error_from_extension_port_retries_original_pending_cycle(failure_port):
    async def scenario():
        source = SequenceSource(
            [
                snapshot_from_feed(
                    gtfs_realtime_pb2.FeedMessage.FromString(protobuf_trip_update())
                ),
                empty_snapshot(),
            ]
        )
        original = datetime(2026, 7, 19, tzinfo=UTC)
        observed_times = []
        published = []
        attempts = {"estimator": 0, "publisher": 0, "serializer": 0}

        def fail_once(port):
            attempts[port] += 1
            if failure_port == port and attempts[port] == 1:
                raise ValueError(f"temporary {port} failure")

        class Estimator(MatchingEstimator):
            async def estimate_many(self, updates, observed_at, max_positions=None):
                observed_times.append((observed_at, max_positions))
                fail_once("estimator")
                return await super().estimate_many(updates, observed_at, max_positions)

        class Publisher:
            async def publish(self, event):
                fail_once("publisher")
                published.append(event)

        def serialize(position):
            fail_once("serializer")
            return position.to_websocket_event()

        worker = TripUpdateIngestionWorker(source, Estimator(), Publisher(), serialize)
        with pytest.raises(ValueError, match="temporary"):
            await worker.run_once(original, max_positions=1)
        assert worker._pending_cycle is not None
        assert source.calls == 1
        # New call arguments must not overwrite the retained cycle's provenance.
        result = await worker.run_once(datetime.max, max_positions=2)
        assert result.position_snapshots_published == 1
        assert observed_times == [(original, 1), (original, 1)]
        assert source.calls == 1
        assert len(published) == 1
        assert published[0]["observed_at"] == "2026-07-19T00:00:00Z"
        assert worker._pending_cycle is None
        await worker.run_once(original + timedelta(seconds=30))
        assert source.calls == 2
        assert len(published) == 2

    asyncio.run(scenario())
