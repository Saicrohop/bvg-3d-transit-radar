from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class StopTimeUpdate:
    """A normalized GTFS-RT update for one scheduled stop."""

    stop_sequence: int | None
    stop_id: str | None
    arrival_time: int | None
    arrival_delay_seconds: int | None
    departure_time: int | None
    departure_delay_seconds: int | None

    def to_estimator_payload(self) -> dict[str, int | str]:
        values: dict[str, int | str | None] = {
            "stop_sequence": self.stop_sequence,
            "stop_id": self.stop_id,
            "arrival_time": self.arrival_time,
            "arrival_delay_seconds": self.arrival_delay_seconds,
            "departure_time": self.departure_time,
            "departure_delay_seconds": self.departure_delay_seconds,
        }
        return {key: value for key, value in values.items() if value is not None}


@dataclass(frozen=True, slots=True)
class TripUpdate:
    """A GTFS-RT TripUpdate independent of its Protobuf transport encoding."""

    entity_id: str
    trip_id: str
    route_id: str
    service_date: date
    feed_timestamp: int | None
    stop_time_updates: tuple[StopTimeUpdate, ...]
