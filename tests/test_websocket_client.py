import asyncio
import json
from io import StringIO

from bvg_radar.websocket_client import receive_position_events


class FakeWebSocket:
    def __init__(self, messages: tuple[str, ...]) -> None:
        self._messages = messages

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for message in self._messages:
            yield message


class FakeConnection:
    def __init__(self, messages: tuple[str, ...]) -> None:
        self._websocket = FakeWebSocket(messages)

    async def __aenter__(self) -> FakeWebSocket:
        return self._websocket

    async def __aexit__(self, *_arguments: object) -> None:
        return None


def test_terminal_client_prints_a_received_estimated_position() -> None:
    event = {
        "type": "vehicle_position",
        "source": "trip_update_interpolation",
        "is_estimated": True,
        "longitude": 13.401,
        "latitude": 52.501,
        "bearing_degrees": 91.5,
        "speed_mps": 8.2,
    }
    output = StringIO()

    received = asyncio.run(
        receive_position_events(
            "ws://example.test/ws/positions",
            output=output,
            max_events=1,
            connect=lambda _url: FakeConnection((json.dumps(event),)),
        )
    )

    assert received == 1
    assert json.loads(output.getvalue()) == event
