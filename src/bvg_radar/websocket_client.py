"""Terminal validation client for the local estimated-position WebSocket."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import sys
from collections.abc import AsyncIterator, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import date, datetime
from typing import Protocol, TextIO

import websockets

DEFAULT_POSITIONS_URL = "ws://127.0.0.1:8000/ws/positions"
MAX_SNAPSHOT_FRAME_BYTES = 8 * 1024 * 1024


_REQUIRED_SNAPSHOT_FIELDS = frozenset(
    {
        "type",
        "schema_version",
        "cycle_id",
        "feed_timestamp",
        "observed_at",
        "positions",
        "statistics",
    }
)
_REQUIRED_POSITION_FIELDS = frozenset(
    {
        "type",
        "source",
        "is_estimated",
        "position_status",
        "timing_source",
        "feed_timestamp",
        "trip_update_timestamp",
        "service_date",
        "vehicle_category",
        "route_short_name",
        "entity_id",
        "trip_id",
        "route_id",
        "shape_id",
        "previous_stop_id",
        "next_stop_id",
        "delay_seconds",
        "estimated_next_arrival",
        "longitude",
        "latitude",
        "bearing_degrees",
        "speed_mps",
        "observed_at",
    }
)
_UTC_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z"
)
_SERVICE_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _is_nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_utc_timestamp(value: object) -> bool:
    if not isinstance(value, str) or _UTC_TIMESTAMP.fullmatch(value) is None:
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_nullable_timestamp(value: object) -> bool:
    return value is None or _is_utc_timestamp(value)


def _is_service_date(value: object) -> bool:
    if not isinstance(value, str) or _SERVICE_DATE.fullmatch(value) is None:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_finite_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _is_position(value: object) -> bool:
    if not isinstance(value, dict) or not _REQUIRED_POSITION_FIELDS <= value.keys():
        return False
    timing_source = value["timing_source"]
    delay = value["delay_seconds"]
    return (
        value["type"] == "vehicle_position"
        and value["source"] == "trip_update_interpolation"
        and value["is_estimated"] is True
        and value["position_status"] == "estimated_from_trip_update"
        and timing_source
        in ("absolute_realtime_time", "realtime_delay", "schedule_only")
        and (delay is None if timing_source == "schedule_only" else type(delay) is int)
        and _is_nullable_timestamp(value["feed_timestamp"])
        and _is_nullable_timestamp(value["trip_update_timestamp"])
        and _is_service_date(value["service_date"])
        and value["vehicle_category"]
        in (None, "u_bahn", "s_bahn", "bus", "tram", "regional")
        and (
            value["route_short_name"] is None
            or isinstance(value["route_short_name"], str)
        )
        and all(
            _is_nonempty_text(value[field])
            for field in (
                "entity_id",
                "trip_id",
                "route_id",
                "shape_id",
                "previous_stop_id",
                "next_stop_id",
            )
        )
        and _is_utc_timestamp(value["estimated_next_arrival"])
        and _is_utc_timestamp(value["observed_at"])
        and _is_finite_number(value["longitude"])
        and abs(value["longitude"]) <= 180
        and _is_finite_number(value["latitude"])
        and abs(value["latitude"]) <= 90
        and _is_finite_number(value["bearing_degrees"])
        and _is_finite_number(value["speed_mps"])
        and value["speed_mps"] >= 0
    )


def _is_snapshot(value: object) -> bool:
    if not isinstance(value, dict) or not _REQUIRED_SNAPSHOT_FIELDS <= value.keys():
        return False
    if (
        value["type"] != "vehicle_position_snapshot"
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or not _is_nonempty_text(value["cycle_id"])
        or not _is_nullable_timestamp(value["feed_timestamp"])
        or not _is_utc_timestamp(value["observed_at"])
        or not isinstance(value["positions"], list)
        or not isinstance(value["statistics"], dict)
    ):
        return False
    positions = value["positions"]
    statistics = value["statistics"]
    for field in (
        "trip_updates_received",
        "positions_estimated",
        "positions_suppressed",
    ):
        if (
            field not in statistics
            or type(statistics[field]) is not int
            or not 0 <= statistics[field] <= 2**53 - 1
        ):
            return False
    if (
        statistics["positions_estimated"] != len(positions)
        or statistics["positions_estimated"] + statistics["positions_suppressed"]
        != statistics["trip_updates_received"]
    ):
        return False
    trip_ids: set[str] = set()
    for position in positions:
        if (
            not _is_position(position)
            or position["trip_id"] in trip_ids
            or position["feed_timestamp"] != value["feed_timestamp"]
            or position["observed_at"] != value["observed_at"]
        ):
            return False
        trip_ids.add(position["trip_id"])
    return True


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _finite_json_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JSON number overflow")
    return number


def parse_position_snapshot(raw_message: str | bytes) -> dict[str, object] | None:
    """Fail closed on an invalid envelope; never salvage individual positions."""
    try:
        event = json.loads(
            raw_message,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
            parse_float=_finite_json_float,
        )
        return event if _is_snapshot(event) else None
    except (ValueError, TypeError, OverflowError, RecursionError):
        return None


class WebSocketMessageStream(Protocol):
    def __aiter__(self) -> AsyncIterator[str]: ...


class WebSocketConnector(Protocol):
    def __call__(
        self, url: str, *, max_size: int
    ) -> AbstractAsyncContextManager[WebSocketMessageStream]: ...


async def receive_position_events(
    url: str,
    *,
    output: TextIO,
    max_events: int | None = None,
    connect: WebSocketConnector = websockets.connect,
) -> int:
    """Print normalized estimated-position messages until the limit or disconnect."""
    if max_events is not None and (type(max_events) is not int or max_events <= 0):
        raise ValueError("max_events must be a positive integer when provided")

    received = 0
    async with connect(url, max_size=MAX_SNAPSHOT_FRAME_BYTES) as websocket:
        async for raw_message in websocket:
            event = parse_position_snapshot(raw_message)
            if event is None:
                continue

            output.write(
                json.dumps(
                    event, separators=(",", ":"), sort_keys=True, allow_nan=False
                )
                + "\n"
            )
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
        help="Stop after this many valid snapshots (including empty); 0 keeps listening.",
    )
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    parsed = parse_arguments(arguments)
    max_events = parsed.max_events or None
    asyncio.run(
        receive_position_events(parsed.url, output=sys.stdout, max_events=max_events)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
