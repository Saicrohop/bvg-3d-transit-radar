from dataclasses import dataclass
from datetime import date
from enum import Enum


class TripScheduleRelationship(str, Enum):
    """Normalized GTFS-RT TripDescriptor schedule relationships."""

    SCHEDULED = "SCHEDULED"
    ADDED = "ADDED"
    UNSCHEDULED = "UNSCHEDULED"
    CANCELED = "CANCELED"
    REPLACEMENT = "REPLACEMENT"
    DUPLICATED = "DUPLICATED"
    DELETED = "DELETED"
    NEW = "NEW"
    UNKNOWN = "UNKNOWN"


class StopScheduleRelationship(str, Enum):
    """Normalized GTFS-RT StopTimeUpdate schedule relationships."""

    SCHEDULED = "SCHEDULED"
    SKIPPED = "SKIPPED"
    NO_DATA = "NO_DATA"
    UNSCHEDULED = "UNSCHEDULED"
    UNKNOWN = "UNKNOWN"


class GtfsRealtimeFetchStatus(str, Enum):
    """Whether a source returned a decoded snapshot or HTTP not-modified."""

    UPDATED = "UPDATED"
    NOT_MODIFIED = "NOT_MODIFIED"


_NON_TIMING_STOP_RELATIONSHIPS = frozenset(
    {
        StopScheduleRelationship.SKIPPED,
        StopScheduleRelationship.NO_DATA,
    }
)


@dataclass(frozen=True, slots=True)
class StopTimeUpdate:
    """A normalized GTFS-RT update for one scheduled stop."""

    stop_sequence: int | None
    stop_id: str | None
    arrival_time: int | None
    arrival_delay_seconds: int | None
    departure_time: int | None
    departure_delay_seconds: int | None
    schedule_relationship: StopScheduleRelationship = (
        StopScheduleRelationship.SCHEDULED
    )

    def to_estimator_payload(self) -> dict[str, int | str]:
        values: dict[str, int | str | None] = {
            "stop_sequence": self.stop_sequence,
            "stop_id": self.stop_id,
        }
        if self.schedule_relationship not in _NON_TIMING_STOP_RELATIONSHIPS:
            values.update(
                {
                    "arrival_time": self.arrival_time,
                    "arrival_delay_seconds": self.arrival_delay_seconds,
                    "departure_time": self.departure_time,
                    "departure_delay_seconds": self.departure_delay_seconds,
                }
            )
        return {key: value for key, value in values.items() if value is not None}


@dataclass(frozen=True, slots=True)
class TripUpdate:
    """A GTFS-RT TripUpdate independent of its Protobuf transport encoding."""

    entity_id: str
    trip_id: str | None
    route_id: str | None
    service_date: date | None
    trip_update_timestamp: int | None
    stop_time_updates: tuple[StopTimeUpdate, ...]
    schedule_relationship: TripScheduleRelationship = (
        TripScheduleRelationship.SCHEDULED
    )

    @property
    def is_static_schedule_matchable(self) -> bool:
        return (
            self.schedule_relationship is TripScheduleRelationship.SCHEDULED
            and bool(self.trip_id)
            and bool(self.route_id)
            and self.service_date is not None
        )


@dataclass(frozen=True, slots=True)
class DeletedFeedEntity:
    """The stable identifier of a GTFS-RT entity explicitly deleted by its feed."""

    entity_id: str


@dataclass(frozen=True, slots=True)
class GtfsRealtimeSnapshot:
    """One successfully decoded GTFS-Realtime feed snapshot."""

    feed_timestamp: int | None
    trip_updates: tuple[TripUpdate, ...]
    deleted_entities: tuple[DeletedFeedEntity, ...] = ()


@dataclass(frozen=True, slots=True)
class GtfsRealtimeFetchResult:
    """Result of one conditional GTFS-Realtime fetch."""

    status: GtfsRealtimeFetchStatus
    snapshot: GtfsRealtimeSnapshot | None

    def __post_init__(self) -> None:
        has_updated_snapshot = (
            self.status is GtfsRealtimeFetchStatus.UPDATED
            and self.snapshot is not None
        )
        is_not_modified = (
            self.status is GtfsRealtimeFetchStatus.NOT_MODIFIED
            and self.snapshot is None
        )
        if not (has_updated_snapshot or is_not_modified):
            raise ValueError("fetch status and snapshot contradict each other")
