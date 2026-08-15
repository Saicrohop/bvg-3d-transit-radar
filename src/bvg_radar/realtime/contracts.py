from dataclasses import dataclass
from datetime import datetime, timezone

from .vehicle_category import VehicleCategory


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("WebSocket timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class EstimatedVehiclePosition:
    """A conservative vehicle-position estimate derived from a TripUpdate."""

    entity_id: str
    trip_id: str
    route_id: str
    shape_id: str
    previous_stop_id: str
    next_stop_id: str
    delay_seconds: int
    estimated_next_arrival: datetime
    longitude: float
    latitude: float
    bearing_degrees: float
    speed_mps: float
    observed_at: datetime
    vehicle_category: VehicleCategory | None = None
    route_short_name: str | None = None

    def to_websocket_event(self) -> dict[str, object]:
        """Return the future WebSocket payload without coupling to FastAPI."""
        return {
            "type": "vehicle_position",
            "source": "trip_update_interpolation",
            "is_estimated": True,
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
