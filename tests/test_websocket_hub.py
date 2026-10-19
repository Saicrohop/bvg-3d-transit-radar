import asyncio

import pytest

from bvg_radar.realtime.websocket import (
    PositionWebSocketHub,
    SnapshotReplayError,
)


class RecordingWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.events: list[dict[str, object]] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, event: dict[str, object]) -> None:
        self.events.append(event)


class SlowWebSocket(RecordingWebSocket):
    def __init__(self) -> None:
        super().__init__()
        self.send_attempts = 0

    async def send_json(self, event: dict[str, object]) -> None:
        self.send_attempts += 1
        await asyncio.Event().wait()


class OrderedWebSocket(RecordingWebSocket):
    def __init__(self) -> None:
        super().__init__()
        self.first_send_started = asyncio.Event()
        self.release_first_send = asyncio.Event()

    async def send_json(self, event: dict[str, object]) -> None:
        if event["cycle_id"] == "cycle-1":
            self.first_send_started.set()
            await self.release_first_send.wait()
        self.events.append(event)


class FailingWebSocket(RecordingWebSocket):
    def __init__(self) -> None:
        super().__init__()
        self.send_attempts = 0

    async def send_json(self, event: dict[str, object]) -> None:
        self.send_attempts += 1
        raise RuntimeError("connection closed")


class MutatingWebSocket(RecordingWebSocket):
    async def send_json(self, event: dict[str, object]) -> None:
        statistics = event["statistics"]
        assert isinstance(statistics, dict)
        statistics["positions_estimated"] = 999
        event["cycle_id"] = "cycle-mutated-by-client"
        await super().send_json(event)


class BlockingReplayWebSocket(RecordingWebSocket):
    def __init__(self) -> None:
        super().__init__()
        self.send_attempts = 0
        self.send_started = asyncio.Event()
        self.release_send = asyncio.Event()

    async def send_json(self, event: dict[str, object]) -> None:
        self.send_attempts += 1
        self.send_started.set()
        await self.release_send.wait()
        await super().send_json(event)


def snapshot_event(cycle_id: str = "cycle-1") -> dict[str, object]:
    return {
        "type": "vehicle_position_snapshot",
        "schema_version": 1,
        "cycle_id": cycle_id,
        "feed_timestamp": "2026-07-19T10:38:20Z",
        "observed_at": "2026-07-19T10:40:00Z",
        "positions": [],
        "statistics": {
            "trip_updates_received": 0,
            "positions_estimated": 0,
            "positions_suppressed": 0,
        },
    }


async def connect_and_publish_to_two_clients() -> tuple[RecordingWebSocket, RecordingWebSocket]:
    hub = PositionWebSocketHub()
    first = RecordingWebSocket()
    second = RecordingWebSocket()

    await hub.connect(first)
    await hub.connect(second)
    await hub.publish(snapshot_event())

    return first, second


def test_websocket_hub_broadcasts_estimated_positions_to_all_clients() -> None:
    first, second = asyncio.run(connect_and_publish_to_two_clients())

    assert first.accepted is True
    assert second.accepted is True
    assert first.events == second.events == [snapshot_event()]


async def connect_after_snapshot_was_published() -> RecordingWebSocket:
    hub = PositionWebSocketHub()
    await hub.publish(snapshot_event("cycle-retained"))
    client = RecordingWebSocket()

    await hub.connect(client)

    return client


def test_websocket_hub_replays_the_latest_snapshot_to_a_new_client() -> None:
    client = asyncio.run(connect_after_snapshot_was_published())

    assert client.events == [snapshot_event("cycle-retained")]


async def publish_with_a_slow_client() -> tuple[RecordingWebSocket, SlowWebSocket]:
    hub = PositionWebSocketHub(send_timeout_seconds=0.01)
    healthy = RecordingWebSocket()
    slow = SlowWebSocket()
    await hub.connect(healthy)
    await hub.connect(slow)

    await asyncio.wait_for(hub.publish(snapshot_event("cycle-1")), timeout=0.1)
    await hub.publish(snapshot_event("cycle-2"))

    return healthy, slow


def test_websocket_hub_times_out_and_removes_a_slow_client() -> None:
    healthy, slow = asyncio.run(publish_with_a_slow_client())

    assert healthy.events == [snapshot_event("cycle-1"), snapshot_event("cycle-2")]
    assert slow.send_attempts == 1


async def publish_after_a_client_disconnects() -> tuple[RecordingWebSocket, FailingWebSocket]:
    hub = PositionWebSocketHub()
    healthy = RecordingWebSocket()
    failed = FailingWebSocket()

    await hub.connect(healthy)
    await hub.connect(failed)
    await hub.publish(snapshot_event())
    await hub.publish(snapshot_event())

    return healthy, failed


def test_websocket_hub_drops_a_failed_client_without_blocking_healthy_clients() -> None:
    healthy, failed = asyncio.run(publish_after_a_client_disconnects())

    assert healthy.events == [snapshot_event(), snapshot_event()]
    assert failed.send_attempts == 1


async def replay_only_the_latest_snapshot() -> RecordingWebSocket:
    hub = PositionWebSocketHub()
    await hub.publish(snapshot_event("cycle-old"))
    await hub.publish(snapshot_event("cycle-latest"))
    client = RecordingWebSocket()

    await hub.connect(client)

    return client


def test_websocket_hub_replays_only_the_latest_snapshot() -> None:
    client = asyncio.run(replay_only_the_latest_snapshot())

    assert client.events == [snapshot_event("cycle-latest")]


async def publish_concurrently() -> OrderedWebSocket:
    hub = PositionWebSocketHub(send_timeout_seconds=0.1)
    client = OrderedWebSocket()
    await hub.connect(client)

    first = asyncio.create_task(hub.publish(snapshot_event("cycle-1")))
    await client.first_send_started.wait()
    second = asyncio.create_task(hub.publish(snapshot_event("cycle-2")))
    await asyncio.sleep(0)
    client.release_first_send.set()
    await asyncio.gather(first, second)

    return client


def test_websocket_hub_serializes_concurrent_snapshot_publications() -> None:
    client = asyncio.run(publish_concurrently())

    assert client.events == [snapshot_event("cycle-1"), snapshot_event("cycle-2")]


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("inf"), float("nan")])
def test_websocket_hub_rejects_an_invalid_send_timeout(timeout: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        PositionWebSocketHub(send_timeout_seconds=timeout)


async def replay_after_the_publisher_mutates_its_payload() -> RecordingWebSocket:
    hub = PositionWebSocketHub()
    event = snapshot_event("cycle-original")
    await hub.publish(event)
    event["cycle_id"] = "cycle-mutated"
    client = RecordingWebSocket()

    await hub.connect(client)

    return client


def test_websocket_hub_retains_a_copy_of_the_published_snapshot() -> None:
    client = asyncio.run(replay_after_the_publisher_mutates_its_payload())

    assert client.events == [snapshot_event("cycle-original")]


async def fail_retained_replay_then_publish_again() -> int:
    hub = PositionWebSocketHub()
    await hub.publish(snapshot_event("cycle-retained"))
    failed = FailingWebSocket()

    with pytest.raises(SnapshotReplayError, match="retained snapshot"):
        await hub.connect(failed)
    await hub.publish(snapshot_event("cycle-next"))

    return failed.send_attempts


def test_websocket_hub_removes_a_client_when_retained_replay_fails() -> None:
    send_attempts = asyncio.run(fail_retained_replay_then_publish_again())

    assert send_attempts == 1


async def mutate_a_fanout_payload_then_replay() -> RecordingWebSocket:
    hub = PositionWebSocketHub()
    mutating = MutatingWebSocket()
    await hub.connect(mutating)
    await hub.publish(snapshot_event("cycle-original"))
    late_client = RecordingWebSocket()

    await hub.connect(late_client)

    return late_client


def test_websocket_hub_isolates_retained_state_from_client_mutation() -> None:
    late_client = asyncio.run(mutate_a_fanout_payload_then_replay())

    assert late_client.events == [snapshot_event("cycle-original")]


async def cancel_retained_replay_then_publish_again() -> int:
    hub = PositionWebSocketHub(send_timeout_seconds=1.0)
    await hub.publish(snapshot_event("cycle-retained"))
    client = BlockingReplayWebSocket()
    connect_task = asyncio.create_task(hub.connect(client))
    await client.send_started.wait()

    connect_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await connect_task
    await hub.publish(snapshot_event("cycle-next"))

    return client.send_attempts


def test_websocket_hub_removes_a_cancelled_replay_client() -> None:
    send_attempts = asyncio.run(cancel_retained_replay_then_publish_again())

    assert send_attempts == 1


async def start_two_retained_replays_without_serializing_them() -> bool:
    hub = PositionWebSocketHub(send_timeout_seconds=0.2)
    await hub.publish(snapshot_event("cycle-retained"))
    first = BlockingReplayWebSocket()
    second = BlockingReplayWebSocket()
    tasks = [asyncio.create_task(hub.connect(client)) for client in (first, second)]
    both_started = False

    try:
        await asyncio.wait_for(
            asyncio.gather(first.send_started.wait(), second.send_started.wait()),
            timeout=0.05,
        )
        both_started = True
    except TimeoutError:
        pass
    finally:
        first.release_send.set()
        second.release_send.set()
        await asyncio.gather(*tasks, return_exceptions=True)

    return both_started


def test_websocket_hub_does_not_serialize_slow_retained_replays() -> None:
    both_started = asyncio.run(start_two_retained_replays_without_serializing_them())

    assert both_started is True


async def wait_for_a_slow_client_to_be_evicted() -> int:
    hub = PositionWebSocketHub(send_timeout_seconds=0.01)
    slow = SlowWebSocket()
    await hub.connect(slow)
    eviction = asyncio.create_task(hub.wait_until_disconnected(slow))

    await hub.publish(snapshot_event("cycle-evicts-slow"))
    await asyncio.wait_for(eviction, timeout=0.05)

    return slow.send_attempts


def test_websocket_hub_notifies_when_a_slow_client_is_evicted() -> None:
    send_attempts = asyncio.run(wait_for_a_slow_client_to_be_evicted())

    assert send_attempts == 1


async def connect_while_a_new_snapshot_is_published() -> list[dict[str, object]]:
    hub = PositionWebSocketHub(send_timeout_seconds=0.5)
    await hub.publish(snapshot_event("cycle-old"))
    client = BlockingReplayWebSocket()

    connect_task = asyncio.create_task(hub.connect(client))
    await client.send_started.wait()

    publish_task = asyncio.create_task(hub.publish(snapshot_event("cycle-new")))
    await asyncio.sleep(0)
    assert publish_task.done() is False

    client.release_send.set()
    await asyncio.gather(connect_task, publish_task)
    return client.events


def test_websocket_hub_orders_retained_replay_before_concurrent_publish() -> None:
    events = asyncio.run(connect_while_a_new_snapshot_is_published())

    assert [event["cycle_id"] for event in events] == ["cycle-old", "cycle-new"]


def test_websocket_hub_exposes_a_defensive_copy_of_latest_snapshot() -> None:
    async def read_latest_snapshot() -> dict[str, object] | None:
        hub = PositionWebSocketHub()
        assert hub.latest_snapshot is None
        published = snapshot_event("cycle-latest")
        await hub.publish(published)
        published["cycle_id"] = "caller-mutated"
        latest = hub.latest_snapshot
        assert latest is not None
        latest["positions"].append({"route_id": "mutation"})
        return hub.latest_snapshot

    latest = asyncio.run(read_latest_snapshot())

    assert latest == snapshot_event("cycle-latest")
