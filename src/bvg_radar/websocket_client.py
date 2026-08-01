"""Terminal validation client for the local estimated-position WebSocket."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Protocol, TextIO

import websockets

DEFAULT_POSITIONS_URL = "ws://127.0.0.1:8000/ws/positions"


class WebSocketMessageStream(Protocol):
    def __aiter__(self) -> AsyncIterator[str]: ...


WebSocketConnector = Callable[
    [str], AbstractAsyncContextManager[WebSocketMessageStream]
]


async def receive_position_events(
    url: str,
    *,
    output: TextIO,
    max_events: int | None = None,
    connect: WebSocketConnector = websockets.connect,
) -> int:
    """Print normalized estimated-position messages until the limit or disconnect."""
    if max_events is not None and max_events <= 0:
        raise ValueError("max_events must be positive when provided")

    received = 0
    async with connect(url) as websocket:
        async for raw_message in websocket:
            event = json.loads(raw_message)
            if (
                event.get("type") != "vehicle_position"
                or event.get("source") != "trip_update_interpolation"
                or event.get("is_estimated") is not True
            ):
                continue

            output.write(json.dumps(event, separators=(",", ":"), sort_keys=True) + "\n")
            output.flush()
            received += 1
            if max_events is not None and received >= max_events:
                return received

    return received


def parse_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print estimated VBB positions received from the local WebSocket."
    )
    parser.add_argument("--url", default=DEFAULT_POSITIONS_URL)
    parser.add_argument(
        "--max-events",
        type=int,
        default=0,
        help="Stop after this many estimated positions; omit or use 0 to keep listening.",
    )
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    parsed = parse_arguments(arguments)
    max_events = parsed.max_events or None
    asyncio.run(receive_position_events(parsed.url, output=sys.stdout, max_events=max_events))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
