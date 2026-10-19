from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal

from .vehicle_category import VehicleCategory

TimingSource = Literal[
    "absolute_realtime_time",
    "realtime_delay",
    "schedule_only",
]
PositionStatus = Literal["estimated_from_trip_update"]
_TIMING_SOURCES = frozenset(
    {"absolute_realtime_time", "realtime_delay", "schedule_only"}
)


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("WebSocket timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _optional_utc_timestamp(value: datetime | None) -> str | None:
    return None if value is None else _utc_timestamp(value)


@dataclass(frozen=True, slots=True)
class EstimatedVehiclePosition:
    """A conservative vehicle-position estimate derived from a TripUpdate."""

    entity_id: str
    trip_id: str
    route_id: str
    shape_id: str
    previous_stop_id: str
    next_stop_id: str
    delay_seconds: int | None
    estimated_next_arrival: datetime
    longitude: float
    latitude: float
    bearing_degrees: float
    speed_mps: float
    observed_at: datetime
    timing_source: TimingSource
    feed_timestamp: datetime | None
    trip_update_timestamp: datetime | None
    service_date: date
    is_estimated: bool
    position_status: PositionStatus
    vehicle_category: VehicleCategory | None = None
    route_short_name: str | None = None

    def __post_init__(self) -> None:
        if self.timing_source not in _TIMING_SOURCES:
            raise ValueError(f"Unsupported timing_source: {self.timing_source!r}")
        if self.timing_source == "schedule_only":
            if self.delay_seconds is not None:
                raise ValueError(
                    "schedule_only positions cannot claim an observed delay"
                )
        elif self.delay_seconds is None:
            raise ValueError(
                "realtime timing sources require an observed delay_seconds"
            )
        elif type(self.delay_seconds) is not int:
            raise ValueError("delay_seconds must be an integer")
        if self.is_estimated is not True:
            raise ValueError("Estimated positions require is_estimated=true")
        if self.position_status != "estimated_from_trip_update":
            raise ValueError(f"Unsupported position_status: {self.position_status!r}")

    def to_websocket_event(self) -> dict[str, object]:
        """Return the normalized position record nested in snapshot payloads."""
        return {
            "type": "vehicle_position",
            "source": "trip_update_interpolation",
            "is_estimated": self.is_estimated,
            "position_status": self.position_status,
            "timing_source": self.timing_source,
            "feed_timestamp": _optional_utc_timestamp(self.feed_timestamp),
            "trip_update_timestamp": _optional_utc_timestamp(
                self.trip_update_timestamp
            ),
            "service_date": self.service_date.isoformat(),
            "vehicle_category": self.vehicle_category,
            "route_short_name": self.route_short_name,
            "entity_id": self.entity_id,
            "trip_id": self.trip_id,
            "route_id": self.route_id,
            "shape_id": self.shape_id,
            "previous_stop_id": self.previous_stop_id,
            "next_stop_id": self.next_stop_id,
            "delay_seconds": self.delay_seconds,
            "estimated_next_arrival": _utc_timestamp(self.estimated_next_arrival),
            "longitude": self.longitude,
            "latitude": self.latitude,
            "bearing_degrees": self.bearing_degrees,
            "speed_mps": self.speed_mps,
            "observed_at": _utc_timestamp(self.observed_at),
        }


@dataclass(frozen=True, slots=True)
class VehiclePositionSnapshot:
    """A complete, versioned set of estimated positions for one feed cycle."""

    cycle_id: str
    feed_timestamp: datetime | None
    observed_at: datetime
    positions: tuple[EstimatedVehiclePosition, ...]
    trip_updates_received: int
    positions_suppressed: int

    def __post_init__(self) -> None:
        if not self.cycle_id.strip():
            raise ValueError("cycle_id must be non-empty")
        _utc_timestamp(self.observed_at)
        if self.feed_timestamp is not None:
            _utc_timestamp(self.feed_timestamp)
        if (
            type(self.trip_updates_received) is not int
            or self.trip_updates_received < 0
            or type(self.positions_suppressed) is not int
            or self.positions_suppressed < 0
            or len(self.positions) + self.positions_suppressed
            != self.trip_updates_received
        ):
            raise ValueError("snapshot statistics are inconsistent")

        trip_ids = tuple(position.trip_id for position in self.positions)
        if len(set(trip_ids)) != len(trip_ids):
            raise ValueError("snapshot contains duplicate trip_id values")
        if any(
            position.feed_timestamp != self.feed_timestamp
            or position.observed_at != self.observed_at
            for position in self.positions
        ):
            raise ValueError("position does not match snapshot provenance")

    def to_websocket_event(
        self,
        serialize_position: Callable[
            [EstimatedVehiclePosition], dict[str, object]
        ]
        | None = None,
    ) -> dict[str, object]:
        position_serializer = (
            EstimatedVehiclePosition.to_websocket_event
            if serialize_position is None
            else serialize_position
        )
        return {
            "type": "vehicle_position_snapshot",
            "schema_version": 1,
            "cycle_id": self.cycle_id,
            "feed_timestamp": _optional_utc_timestamp(self.feed_timestamp),
            "observed_at": _utc_timestamp(self.observed_at),
            "positions": [
                position_serializer(position) for position in self.positions
            ],
            "statistics": {
                "trip_updates_received": self.trip_updates_received,
                "positions_estimated": len(self.positions),
                "positions_suppressed": self.positions_suppressed,
            },
        }
