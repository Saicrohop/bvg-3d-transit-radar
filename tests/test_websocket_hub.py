import asyncio

from bvg_radar.realtime.websocket import PositionWebSocketHub


class RecordingWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.events: list[dict[str, object]] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, event: dict[str, object]) -> None:
        self.events.append(event)


class FailingWebSocket(RecordingWebSocket):
    def __init__(self) -> None:
        super().__init__()
        self.send_attempts = 0

    async def send_json(self, event: dict[str, object]) -> None:
        self.send_attempts += 1
        raise RuntimeError("connection closed")


def estimated_event() -> dict[str, object]:
    return {
        "type": "vehicle_position",
        "source": "trip_update_interpolation",
        "is_estimated": True,
        "longitude": 13.401,
        "latitude": 52.501,
        "bearing_degrees": 91.5,
        "speed_mps": 8.2,
    }


async def connect_and_publish_to_two_clients() -> tuple[RecordingWebSocket, RecordingWebSocket]:
    hub = PositionWebSocketHub()
    first = RecordingWebSocket()
    second = RecordingWebSocket()

    await hub.connect(first)
    await hub.connect(second)
    await hub.publish(estimated_event())

    return first, second


def test_websocket_hub_broadcasts_estimated_positions_to_all_clients() -> None:
    first, second = asyncio.run(connect_and_publish_to_two_clients())

    assert first.accepted is True
    assert second.accepted is True
    assert first.events == second.events == [estimated_event()]


async def publish_after_a_client_disconnects() -> tuple[RecordingWebSocket, FailingWebSocket]:
    hub = PositionWebSocketHub()
    healthy = RecordingWebSocket()
    failed = FailingWebSocket()

    await hub.connect(healthy)
    await hub.connect(failed)
    await hub.publish(estimated_event())
    await hub.publish(estimated_event())

    return healthy, failed


def test_websocket_hub_drops_a_failed_client_without_blocking_healthy_clients() -> None:
    healthy, failed = asyncio.run(publish_after_a_client_disconnects())

    assert healthy.events == [estimated_event(), estimated_event()]
    assert failed.send_attempts == 1
