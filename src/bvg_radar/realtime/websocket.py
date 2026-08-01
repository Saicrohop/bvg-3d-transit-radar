"""WebSocket output adapter for normalized estimated-position events."""

from __future__ import annotations

import asyncio
from typing import Protocol

from .worker import PositionEventPublisher


class WebSocketConnection(Protocol):
    async def accept(self) -> None: ...

    async def send_json(self, data: dict[str, object]) -> None: ...


class PositionWebSocketHub(PositionEventPublisher):
    """Fan out worker events to every connected WebSocket client."""

    def __init__(self) -> None:
        self._connections: set[WebSocketConnection] = set()
        self._connections_lock = asyncio.Lock()

    async def connect(self, connection: WebSocketConnection) -> None:
        await connection.accept()
        async with self._connections_lock:
            self._connections.add(connection)

    async def disconnect(self, connection: WebSocketConnection) -> None:
        async with self._connections_lock:
            self._connections.discard(connection)

    async def publish(self, event: dict[str, object]) -> None:
        async with self._connections_lock:
            connections = tuple(self._connections)

        outcomes = await asyncio.gather(
            *(connection.send_json(event) for connection in connections),
            return_exceptions=True,
        )
        disconnected = {
            connection
            for connection, outcome in zip(connections, outcomes, strict=True)
            if isinstance(outcome, Exception)
        }
        if disconnected:
            async with self._connections_lock:
                self._connections.difference_update(disconnected)
