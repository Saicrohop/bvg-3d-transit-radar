import asyncio
import copy
import json
from datetime import UTC, date, datetime
from io import StringIO

import pytest

from bvg_radar.realtime.contracts import (
    EstimatedVehiclePosition,
    VehiclePositionSnapshot,
)
from bvg_radar.websocket_client import receive_position_events


class FakeWebSocket:
    def __init__(self, messages):
        self._messages = messages

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for message in self._messages:
            yield message


class FakeConnection:
    def __init__(self, messages):
        self._websocket = FakeWebSocket(messages)

    async def __aenter__(self):
        return self._websocket

    async def __aexit__(self, *_arguments):
        return None


def position():
    observed = datetime(2026, 10, 14, 10, tzinfo=UTC)
    return EstimatedVehiclePosition(
        entity_id="entity-42",
        trip_id="trip-42",
        route_id="route-7",
        shape_id="shape-42",
        previous_stop_id="stop-1",
        next_stop_id="stop-2",
        delay_seconds=75,
        estimated_next_arrival=observed,
        longitude=13.401,
        latitude=52.501,
        bearing_degrees=91.5,
        speed_mps=8.2,
        observed_at=observed,
        timing_source="realtime_delay",
        feed_timestamp=observed,
        trip_update_timestamp=observed,
        service_date=date(2026, 10, 14),
        is_estimated=True,
        position_status="estimated_from_trip_update",
        vehicle_category="bus",
        route_short_name="M42",
    )


def snapshot(empty=False):
    estimate = position()
    return VehiclePositionSnapshot(
        cycle_id="cycle-42",
        feed_timestamp=estimate.feed_timestamp,
        observed_at=estimate.observed_at,
        positions=() if empty else (estimate,),
        trip_updates_received=0 if empty else 1,
        positions_suppressed=0,
    ).to_websocket_event()


def receive(messages, max_events=None):
    output = StringIO()
    received = asyncio.run(
        receive_position_events(
            "ws://example.test/ws/positions",
            output=output,
            max_events=max_events,
            connect=lambda _url, **_kwargs: FakeConnection(messages),
        )
    )
    return received, [json.loads(line) for line in output.getvalue().splitlines()]


def test_terminal_client_prints_complete_v1_snapshots_including_authoritative_empty():
    first, empty = snapshot(), snapshot(empty=True)
    count, printed = receive([json.dumps(first), json.dumps(empty)], max_events=2)
    assert count == 2
    assert printed == [first, empty]


def test_max_events_counts_envelopes_not_positions():
    first = snapshot()
    second_position = dict(first["positions"][0], trip_id="trip-43")
    first["positions"].append(second_position)
    first["statistics"].update(trip_updates_received=2, positions_estimated=2)
    count, printed = receive(
        [json.dumps(first), json.dumps(snapshot(empty=True))], max_events=1
    )
    assert count == 1
    assert printed == [first]


MALFORMED_SNAPSHOTS = [
    ("schema_version", True),
    ("schema_version", 1.0),
    ("schema_version", 2),
    ("cycle_id", " "),
    ("cycle_id", 42),
    ("positions", {}),
    ("statistics", None),
    ("observed_at", "2026-02-30T10:00:00Z"),
    ("observed_at", "2026-10-14T10:00:00+00:00"),
    ("feed_timestamp", 42),
]
MALFORMED_POSITIONS = [
    ("type", "vehicle_position_snapshot"),
    ("source", "gps"),
    ("is_estimated", 1),
    ("position_status", "observed"),
    ("timing_source", "gps"),
    ("delay_seconds", True),
    ("delay_seconds", 1.5),
    ("delay_seconds", None),
    ("trip_id", ""),
    ("trip_id", "  "),
    ("route_id", []),
    ("entity_id", None),
    ("shape_id", ""),
    ("previous_stop_id", 2),
    ("next_stop_id", {}),
    ("longitude", True),
    ("longitude", "13.4"),
    ("longitude", 181),
    ("latitude", -91),
    ("speed_mps", -1),
    ("speed_mps", float("inf")),
    ("bearing_degrees", float("nan")),
    ("bearing_degrees", float("-inf")),
    ("observed_at", "2026-10-14T10:00:01Z"),
    ("feed_timestamp", None),
    ("trip_update_timestamp", "invalid"),
    ("estimated_next_arrival", None),
    ("service_date", "2026-02-30"),
    ("vehicle_category", []),
    ("route_short_name", 42),
]


@pytest.mark.parametrize("field,value", MALFORMED_SNAPSHOTS)
def test_terminal_client_rejects_malformed_snapshot(field, value):
    event = snapshot()
    event[field] = value
    assert receive([json.dumps(event)]) == (0, [])


@pytest.mark.parametrize("field,value", MALFORMED_POSITIONS)
def test_terminal_client_rejects_whole_snapshot_for_invalid_nested_position(
    field, value
):
    event = snapshot()
    event["positions"][0][field] = value
    assert receive([json.dumps(event)]) == (0, [])


@pytest.mark.parametrize("value", [True, -1, 1.0, "1", None])
@pytest.mark.parametrize(
    "field", ["trip_updates_received", "positions_estimated", "positions_suppressed"]
)
def test_terminal_client_requires_nonnegative_integer_statistics(field, value):
    event = snapshot()
    event["statistics"][field] = value
    assert receive([json.dumps(event)]) == (0, [])


@pytest.mark.parametrize("field", list(snapshot()))
def test_terminal_client_requires_every_snapshot_field(field):
    event = snapshot()
    del event[field]
    assert receive([json.dumps(event)]) == (0, [])


@pytest.mark.parametrize("field", list(snapshot()["positions"][0]))
def test_terminal_client_requires_every_position_field(field):
    event = snapshot()
    del event["positions"][0][field]
    assert receive([json.dumps(event)]) == (0, [])


def test_terminal_client_rejects_duplicate_trip_ids():
    event = snapshot()
    event["positions"].append(copy.deepcopy(event["positions"][0]))
    event["statistics"].update(trip_updates_received=2, positions_estimated=2)
    assert receive([json.dumps(event)]) == (0, [])


def test_terminal_client_rejects_inconsistent_statistics():
    event = snapshot()
    event["statistics"]["positions_suppressed"] = 1
    assert receive([json.dumps(event)]) == (0, [])


@pytest.mark.parametrize(
    "raw", ["{invalid", "null", "[]", "42", '"string"', "true", b"\xff"]
)
def test_terminal_client_skips_malformed_json_and_continues_to_valid_envelope(raw):
    event = snapshot(empty=True)
    assert receive([raw, json.dumps(event)], max_events=1) == (1, [event])


def test_terminal_client_rejects_duplicate_json_keys():
    event = snapshot(empty=True)
    raw = json.dumps(event).replace(
        '"schema_version": 1', '"schema_version": 2, "schema_version": 1'
    )
    assert receive([raw]) == (0, [])


def test_terminal_client_accepts_schedule_only_nullable_provenance():
    event = snapshot()
    event["feed_timestamp"] = None
    event["positions"][0].update(
        feed_timestamp=None,
        trip_update_timestamp=None,
        timing_source="schedule_only",
        delay_seconds=None,
        vehicle_category=None,
        route_short_name=None,
    )
    assert receive([json.dumps(event)]) == (1, [event])


def test_terminal_client_configures_transport_for_snapshots_larger_than_one_mib():
    event = snapshot()
    template = event["positions"][0]
    event["positions"] = [
        dict(template, trip_id=f"trip-{index}") for index in range(1600)
    ]
    event["statistics"].update(trip_updates_received=1600, positions_estimated=1600)
    raw = json.dumps(event)
    size = len(raw.encode("utf-8"))
    assert size > 1024 * 1024
    output = StringIO()
    limits = []

    def connect(_url, *, max_size=1024 * 1024):
        limits.append(max_size)
        assert max_size >= 8 * 1024 * 1024
        assert size <= max_size
        return FakeConnection([raw])

    count = asyncio.run(
        receive_position_events(
            "ws://example.test/ws/positions",
            output=output,
            max_events=1,
            connect=connect,
        )
    )
    assert count == 1
    assert limits == [8 * 1024 * 1024]
    assert json.loads(output.getvalue()) == event


def test_worker_producer_snapshot_is_consumed_intact_by_terminal_client():
    from dataclasses import replace

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

    estimate = position()

    class Source:
        async def fetch(self):
            return GtfsRealtimeFetchResult(
                status=GtfsRealtimeFetchStatus.UPDATED,
                snapshot=GtfsRealtimeSnapshot(
                    feed_timestamp=int(estimate.observed_at.timestamp()),
                    trip_updates=(
                        TripUpdate(
                            entity_id=estimate.entity_id,
                            trip_id=estimate.trip_id,
                            route_id=estimate.route_id,
                            service_date=estimate.service_date,
                            trip_update_timestamp=None,
                            stop_time_updates=(),
                        ),
                    ),
                ),
            )

    class Estimator:
        async def estimate_many(self, _updates, observed_at, max_positions=None):
            return (replace(estimate, observed_at=observed_at),)

    async def cycle():
        queue = asyncio.Queue()
        worker = TripUpdateIngestionWorker(
            Source(), Estimator(), AsyncQueuePositionEventPublisher(queue)
        )
        await worker.run_once(estimate.observed_at)
        return queue.get_nowait()

    produced = asyncio.run(cycle())
    assert receive([json.dumps(produced)]) == (1, [produced])


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, float("nan"), float("inf")])
def test_terminal_client_requires_positive_integer_envelope_limit(limit):
    with pytest.raises(ValueError, match="max_events"):
        receive([], max_events=limit)


def test_terminal_client_rejects_json_float_overflow_even_in_extension_fields():
    raw = json.dumps(snapshot(empty=True))[:-1] + ', "extension": 1e400}'
    assert receive([raw]) == (0, [])


def test_terminal_client_rejects_statistics_outside_safe_json_integer_range():
    event = snapshot(empty=True)
    event["statistics"].update(trip_updates_received=2**53, positions_suppressed=2**53)
    assert receive([json.dumps(event)]) == (0, [])


def test_terminal_client_rejects_schedule_only_observed_delay():
    event = snapshot()
    event["positions"][0]["timing_source"] = "schedule_only"
    assert receive([json.dumps(event)]) == (0, [])
