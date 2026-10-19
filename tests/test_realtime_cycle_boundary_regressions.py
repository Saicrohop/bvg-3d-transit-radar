"""Persist the backend review's in-memory cycle-boundary probes."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone, tzinfo

import pytest
from test_realtime_invalid_cycle_recovery import RecordingPublisher, SequenceSource
from test_trip_update_worker import AllMatchingEstimator, trip_update

from bvg_radar.realtime.models import GtfsRealtimeSnapshot, StopTimeUpdate
from bvg_radar.realtime.normalization import InvalidGtfsRealtimeTimestamp
from bvg_radar.realtime.source import GtfsRealtimeFetchError
from bvg_radar.realtime.worker import InvalidIngestionCycleError, TripUpdateIngestionWorker

OBSERVED_AT = datetime(2026, 7, 19, 10, 43, tzinfo=UTC)


@pytest.fixture
def boundary_snapshots():
    snapshots = []
    for minute, label in enumerate(("initial", "corrected", "following"), start=40):
        feed_timestamp = int(datetime(2026, 7, 19, 10, minute, tzinfo=UTC).timestamp())
        stop = StopTimeUpdate(
            stop_sequence=1,
            stop_id=f"stop-p13a-{label}",
            arrival_time=feed_timestamp + 30,
            arrival_delay_seconds=None,
            departure_time=feed_timestamp + 45,
            departure_delay_seconds=None,
        )
        updates = tuple(
            replace(
                trip_update(f"p13a-{label}-{index}"),
                trip_update_timestamp=feed_timestamp - 5,
                stop_time_updates=(stop,),
            )
            for index in (1, 2)
        )
        snapshots.append(GtfsRealtimeSnapshot(feed_timestamp, updates))
    return tuple(snapshots)


class BoundaryEstimator(AllMatchingEstimator):
    def __init__(self):
        self.calls = []

    async def estimate_many(self, updates, observed_at, max_positions=None):
        self.calls.append((updates, observed_at, max_positions))
        return await super().estimate_many(updates, observed_at, max_positions)


def assert_published_cycle(event, snapshot, observed_at, position_count):
    feed_time = datetime.fromtimestamp(snapshot.feed_timestamp, UTC)
    assert event["type"] == "vehicle_position_snapshot"
    assert event["schema_version"] == 1
    assert event["observed_at"] == observed_at.astimezone(UTC).isoformat().replace(
        "+00:00", "Z"
    )
    assert event["feed_timestamp"] == feed_time.isoformat().replace("+00:00", "Z")
    assert event["statistics"] == {
        "trip_updates_received": 2,
        "positions_estimated": position_count,
        "positions_suppressed": 2 - position_count,
    }
    expected_updates = snapshot.trip_updates[:position_count]
    assert [position["entity_id"] for position in event["positions"]] == [
        update.entity_id for update in expected_updates
    ]
    for position, update in zip(event["positions"], expected_updates, strict=True):
        assert position["trip_id"] == update.trip_id
        assert position["observed_at"] == event["observed_at"]
        assert position["feed_timestamp"] == event["feed_timestamp"]
        update_time = datetime.fromtimestamp(update.trip_update_timestamp, UTC)
        assert position["trip_update_timestamp"] == update_time.isoformat().replace(
            "+00:00", "Z"
        )


@pytest.mark.parametrize("field", ["feed", "trip_update", "arrival", "departure"])
@pytest.mark.parametrize(
    "malformed_timestamp",
    [
        pytest.param(True, id="bool-true"),
        pytest.param(False, id="bool-false"),
        pytest.param(1_784_457_600.0, id="integral-float"),
        pytest.param("1784457600", id="numeric-string"),
    ],
)
def test_malformed_custom_source_timestamp_is_discarded_before_estimation(
    boundary_snapshots, field, malformed_timestamp
):
    async def scenario():
        initial, corrected, _following = boundary_snapshots
        if field == "feed":
            invalid = replace(initial, feed_timestamp=malformed_timestamp)
        else:
            # Validate even the trailing update beyond max_positions=1.
            update = initial.trip_updates[-1]
            if field == "trip_update":
                update = replace(update, trip_update_timestamp=malformed_timestamp)
            else:
                stop = replace(
                    update.stop_time_updates[0],
                    **{f"{field}_time": malformed_timestamp},
                )
                update = replace(update, stop_time_updates=(stop,))
            invalid = replace(initial, trip_updates=(initial.trip_updates[0], update))
        source = SequenceSource([invalid, corrected])
        estimator = BoundaryEstimator()
        publisher = RecordingPublisher()
        worker = TripUpdateIngestionWorker(source, estimator, publisher)

        with pytest.raises(GtfsRealtimeFetchError, match="invalid timestamp") as raised:
            await worker.run_once(OBSERVED_AT, max_positions=1)
        assert isinstance(raised.value.__cause__, InvalidGtfsRealtimeTimestamp)
        assert "must be an integer" in str(raised.value.__cause__)
        assert source.calls == 1
        assert estimator.calls == []
        assert publisher.events == []
        assert worker._pending_cycle is None

        recovered_at = OBSERVED_AT + timedelta(seconds=15)
        recovered = await worker.run_once(recovered_at, max_positions=2)
        assert recovered.position_snapshots_published == 1
        assert recovered.feed_timestamp == corrected.feed_timestamp
        assert source.calls == 2
        assert estimator.calls == [(corrected.trip_updates, recovered_at, 2)]
        assert len(publisher.events) == 1
        assert_published_cycle(publisher.events[0], corrected, recovered_at, 2)

    asyncio.run(scenario())


class MissingUtcOffset(tzinfo):
    def utcoffset(self, _value):
        return None


def test_missing_utc_offset_is_rejected_before_fetch_and_allows_next_cycle(
    boundary_snapshots,
):
    async def scenario():
        initial = boundary_snapshots[0]
        source = SequenceSource([initial])
        estimator = BoundaryEstimator()
        publisher = RecordingPublisher()
        worker = TripUpdateIngestionWorker(source, estimator, publisher)
        invalid_time = OBSERVED_AT.replace(tzinfo=MissingUtcOffset())
        assert invalid_time.tzinfo is not None
        assert invalid_time.utcoffset() is None

        with pytest.raises(InvalidIngestionCycleError, match="observed_at") as raised:
            await worker.run_once(invalid_time, max_positions=1)
        assert isinstance(raised.value.__cause__, ValueError)
        assert str(raised.value.__cause__) == "missing UTC offset"
        assert source.calls == 0
        assert estimator.calls == []
        assert publisher.events == []
        assert worker._pending_cycle is None

        recovered = await worker.run_once(OBSERVED_AT, max_positions=2)
        assert recovered.position_snapshots_published == 1
        assert source.calls == 1
        assert estimator.calls == [(initial.trip_updates, OBSERVED_AT, 2)]
        assert len(publisher.events) == 1
        assert_published_cycle(publisher.events[0], initial, OBSERVED_AT, 2)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("observed_at", "expected_utc"),
    [
        pytest.param(
            datetime(2026, 7, 19, 16, 10, tzinfo=timezone(timedelta(hours=5, minutes=30))),
            "2026-07-19T10:40:00Z",
            id="positive-fractional-offset",
        ),
        pytest.param(
            datetime(2026, 7, 18, 23, 10, tzinfo=timezone(timedelta(hours=-3, minutes=-30))),
            "2026-07-19T02:40:00Z",
            id="negative-offset-utc-date-rollover",
        ),
    ],
)
def test_non_utc_observed_at_is_normalized_in_envelope_and_position(
    boundary_snapshots, observed_at, expected_utc
):
    async def scenario():
        initial = boundary_snapshots[0]
        source = SequenceSource([initial])
        estimator = BoundaryEstimator()
        publisher = RecordingPublisher()
        worker = TripUpdateIngestionWorker(source, estimator, publisher)

        result = await worker.run_once(observed_at, max_positions=1)
        assert result.position_snapshots_published == 1
        assert source.calls == 1
        assert estimator.calls == [(initial.trip_updates, observed_at, 1)]
        assert estimator.calls[0][1] is observed_at
        assert len(publisher.events) == 1
        event = publisher.events[0]
        assert event["observed_at"] == expected_utc
        assert event["positions"][0]["observed_at"] == expected_utc
        assert_published_cycle(event, initial, observed_at, 1)
        assert worker._pending_cycle is None

    asyncio.run(scenario())


@pytest.mark.parametrize("field", ["estimated_next_arrival", "trip_update_timestamp"])
@pytest.mark.parametrize(
    "overflow_time",
    [
        pytest.param(
            datetime.min.replace(tzinfo=timezone(timedelta(hours=14))),
            id="utc-underflow",
        ),
        pytest.param(
            datetime.max.replace(tzinfo=timezone(timedelta(hours=-12))),
            id="utc-overflow",
        ),
    ],
)
def test_position_utc_conversion_overflow_releases_cycle_for_corrected_feed(
    boundary_snapshots, field, overflow_time
):
    async def scenario():
        initial, corrected, _following = boundary_snapshots

        class OverflowOnceEstimator(BoundaryEstimator):
            async def estimate_many(self, updates, observed_at, max_positions=None):
                positions = await super().estimate_many(updates, observed_at, max_positions)
                if len(self.calls) == 1:
                    return (replace(positions[0], **{field: overflow_time}),)
                return positions

        source = SequenceSource([initial, corrected])
        estimator = OverflowOnceEstimator()
        publisher = RecordingPublisher()
        worker = TripUpdateIngestionWorker(source, estimator, publisher)

        with pytest.raises(
            InvalidIngestionCycleError, match="invalid vehicle position contract"
        ) as raised:
            await worker.run_once(OBSERVED_AT, max_positions=1)
        assert isinstance(raised.value.__cause__, OverflowError)
        assert source.calls == 1
        assert publisher.events == []
        assert worker._pending_cycle is None

        recovered_at = OBSERVED_AT + timedelta(seconds=15)
        recovered = await worker.run_once(recovered_at, max_positions=2)
        assert recovered.position_snapshots_published == 1
        assert source.calls == 2
        assert estimator.calls == [
            (initial.trip_updates, OBSERVED_AT, 1),
            (corrected.trip_updates, recovered_at, 2),
        ]
        assert len(publisher.events) == 1
        assert_published_cycle(publisher.events[0], corrected, recovered_at, 2)

    asyncio.run(scenario())


def test_custom_serializer_typed_rejection_discards_but_transient_retains_provenance(
    boundary_snapshots,
):
    async def scenario():
        initial, corrected, following = boundary_snapshots
        source = SequenceSource(boundary_snapshots)
        estimator = BoundaryEstimator()
        publisher = RecordingPublisher()
        permanent_error = InvalidIngestionCycleError("p13a deterministic serializer rejection")
        transient_error = ValueError("p13a temporary serializer outage")
        serialized_positions = []

        def serialize(position):
            serialized_positions.append(position)
            if len(serialized_positions) == 1:
                raise permanent_error
            if len(serialized_positions) == 2:
                raise transient_error
            return position.to_websocket_event()

        worker = TripUpdateIngestionWorker(source, estimator, publisher, serialize)
        with pytest.raises(InvalidIngestionCycleError) as permanent:
            await worker.run_once(OBSERVED_AT, max_positions=2)
        assert permanent.value is permanent_error
        assert source.calls == 1
        assert publisher.events == []
        assert worker._pending_cycle is None

        original_retry_time = OBSERVED_AT + timedelta(seconds=15)
        with pytest.raises(ValueError) as transient:
            await worker.run_once(original_retry_time, max_positions=1)
        assert transient.value is transient_error
        assert source.calls == 2
        assert publisher.events == []
        assert worker._pending_cycle is not None

        recovered = await worker.run_once(
            OBSERVED_AT + timedelta(seconds=30), max_positions=2
        )
        assert recovered.position_snapshots_published == 1
        assert recovered.feed_timestamp == corrected.feed_timestamp
        assert source.calls == 2
        assert len(publisher.events) == 1
        assert serialized_positions[1] == serialized_positions[2]
        assert_published_cycle(publisher.events[0], corrected, original_retry_time, 1)
        assert worker._pending_cycle is None

        following_time = OBSERVED_AT + timedelta(seconds=45)
        result = await worker.run_once(following_time, max_positions=2)
        assert result.position_snapshots_published == 1
        assert result.feed_timestamp == following.feed_timestamp
        assert source.calls == 3
        assert estimator.calls == [
            (initial.trip_updates, OBSERVED_AT, 2),
            (corrected.trip_updates, original_retry_time, 1),
            (corrected.trip_updates, original_retry_time, 1),
            (following.trip_updates, following_time, 2),
        ]
        assert len(publisher.events) == 2
        assert_published_cycle(publisher.events[1], following, following_time, 2)
        assert publisher.events[0]["cycle_id"] != publisher.events[1]["cycle_id"]
        assert worker._pending_cycle is None

    asyncio.run(scenario())
