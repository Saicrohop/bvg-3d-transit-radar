"""WebSocket output adapter for versioned position snapshots."""

from __future__ import annotations

import asyncio
import math
from copy import deepcopy
from dataclasses import dataclass
from typing import Protocol

from .worker import PositionEventPublisher


class WebSocketConnection(Protocol):
    async def accept(self) -> None: ...

    async def send_json(self, data: dict[str, object]) -> None: ...


class SnapshotReplayError(ConnectionError):
    """Raised when a retained snapshot cannot be replayed to a new client."""


@dataclass(slots=True)
class _ConnectionState:
    send_lock: asyncio.Lock
    disconnected: asyncio.Event


class PositionWebSocketHub(PositionEventPublisher):
    """Retain and fan out the latest complete position snapshot."""

    def __init__(self, send_timeout_seconds: float = 1.0) -> None:
        if (
            not math.isfinite(send_timeout_seconds)
            or send_timeout_seconds <= 0
        ):
            raise ValueError("send_timeout_seconds must be finite and positive")
        self._send_timeout_seconds = send_timeout_seconds
        self._connections: dict[WebSocketConnection, _ConnectionState] = {}
        self._connections_lock = asyncio.Lock()
        self._publish_lock = asyncio.Lock()
        self._latest_snapshot: dict[str, object] | None = None

    @property
    def latest_snapshot(self) -> dict[str, object] | None:
        """Return a defensive copy of the retained snapshot for read APIs."""
        return deepcopy(self._latest_snapshot)

    async def connect(self, connection: WebSocketConnection) -> None:
        await connection.accept()
        state = _ConnectionState(asyncio.Lock(), asyncio.Event())
        await state.send_lock.acquire()
        try:
            async with self._connections_lock:
                self._connections[connection] = state
                retained_snapshot = deepcopy(self._latest_snapshot)

            if retained_snapshot is not None:
                await self._send_without_lock(connection, retained_snapshot)

            async with self._connections_lock:
                if self._connections.get(connection) is not state:
                    raise ConnectionError(
                        "connection was evicted during retained snapshot replay"
                    )
        except asyncio.CancelledError:
            await self._remove_connection(connection, expected_state=state)
            raise
        except Exception as error:
            await self._remove_connection(connection, expected_state=state)
            raise SnapshotReplayError("retained snapshot replay failed") from error
        finally:
            state.send_lock.release()

    async def disconnect(self, connection: WebSocketConnection) -> None:
        await self._remove_connection(connection)

    async def wait_until_disconnected(
        self,
        connection: WebSocketConnection,
    ) -> None:
        """Wait until the hub removes a registered connection."""
        async with self._connections_lock:
            state = self._connections.get(connection)
        if state is not None:
            await state.disconnected.wait()

    async def publish(self, event: dict[str, object]) -> None:
        snapshot = deepcopy(event)
        async with self._publish_lock:
            async with self._connections_lock:
                self._latest_snapshot = snapshot
                connections = tuple(self._connections.items())

            outcomes = await asyncio.gather(
                *(
                    self._send_registered(connection, state, snapshot)
                    for connection, state in connections
                ),
                return_exceptions=True,
            )
            disconnected = [
                (connection, state)
                for (connection, state), outcome in zip(
                    connections,
                    outcomes,
                    strict=True,
                )
                if isinstance(outcome, BaseException)
            ]
            for connection, state in disconnected:
                await self._remove_connection(connection, expected_state=state)

    async def _send_registered(
        self,
        connection: WebSocketConnection,
        state: _ConnectionState,
        snapshot: dict[str, object],
    ) -> None:
        payload = deepcopy(snapshot)

        async def send_if_still_registered() -> None:
            async with state.send_lock:
                async with self._connections_lock:
                    if self._connections.get(connection) is not state:
                        return
                await connection.send_json(payload)

        await asyncio.wait_for(
            send_if_still_registered(),
            timeout=self._send_timeout_seconds,
        )

    async def _send_without_lock(
        self,
        connection: WebSocketConnection,
        snapshot: dict[str, object],
    ) -> None:
        await asyncio.wait_for(
            connection.send_json(deepcopy(snapshot)),
            timeout=self._send_timeout_seconds,
        )

    async def _remove_connection(
        self,
        connection: WebSocketConnection,
        *,
        expected_state: _ConnectionState | None = None,
    ) -> None:
        async with self._connections_lock:
            state = self._connections.get(connection)
            if state is None or (
                expected_state is not None and state is not expected_state
            ):
                return
            del self._connections[connection]
            state.disconnected.set()
