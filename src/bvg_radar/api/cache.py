from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from time import monotonic
from typing import Callable


class RoutePathCache:
    """Small process-local TTL cache for immutable GTFS route geometry."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 60.0,
        max_entries: int = 64,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if ttl_seconds <= 0 or max_entries <= 0:
            raise ValueError("cache bounds must be positive")
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._items: OrderedDict[str, tuple[float, dict[str, object]]] = OrderedDict()

    def get(self, key: str) -> dict[str, object] | None:
        cached = self._items.get(key)
        if cached is None:
            return None
        expires_at, value = cached
        if expires_at <= self._clock():
            del self._items[key]
            return None
        self._items.move_to_end(key)
        return deepcopy(value)

    def set(self, key: str, value: dict[str, object]) -> None:
        self._items[key] = (self._clock() + self._ttl_seconds, deepcopy(value))
        self._items.move_to_end(key)
        while len(self._items) > self._max_entries:
            self._items.popitem(last=False)
