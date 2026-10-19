from datetime import UTC, date, datetime

from google.protobuf.message import Message
from google.protobuf.unknown_fields import UnknownFieldSet
from google.transit import gtfs_realtime_pb2

from .models import (
    DeletedFeedEntity,
    GtfsRealtimeSnapshot,
    StopScheduleRelationship,
    StopTimeUpdate,
    TripScheduleRelationship,
    TripUpdate,
)

_TRIP_SCHEDULE_RELATIONSHIPS = {
    gtfs_realtime_pb2.TripDescriptor.SCHEDULED: TripScheduleRelationship.SCHEDULED,
    gtfs_realtime_pb2.TripDescriptor.ADDED: TripScheduleRelationship.ADDED,
    gtfs_realtime_pb2.TripDescriptor.UNSCHEDULED: TripScheduleRelationship.UNSCHEDULED,
    gtfs_realtime_pb2.TripDescriptor.CANCELED: TripScheduleRelationship.CANCELED,
    gtfs_realtime_pb2.TripDescriptor.REPLACEMENT: TripScheduleRelationship.REPLACEMENT,
    gtfs_realtime_pb2.TripDescriptor.DUPLICATED: TripScheduleRelationship.DUPLICATED,
}

# gtfs-realtime-bindings 1.0.0 predates these current core enum values.
_CURRENT_TRIP_RELATIONSHIPS_MISSING_FROM_BINDING = {
    7: TripScheduleRelationship.DELETED,
    8: TripScheduleRelationship.NEW,
}

_STOP_SCHEDULE_RELATIONSHIPS = {
    gtfs_realtime_pb2.TripUpdate.StopTimeUpdate.SCHEDULED: (
        StopScheduleRelationship.SCHEDULED
    ),
    gtfs_realtime_pb2.TripUpdate.StopTimeUpdate.SKIPPED: (
        StopScheduleRelationship.SKIPPED
    ),
    gtfs_realtime_pb2.TripUpdate.StopTimeUpdate.NO_DATA: (
        StopScheduleRelationship.NO_DATA
    ),
    gtfs_realtime_pb2.TripUpdate.StopTimeUpdate.UNSCHEDULED: (
        StopScheduleRelationship.UNSCHEDULED
    ),
}

MAX_STOP_SEQUENCE = 2**31 - 1
# Leave headroom below PostgreSQL INTEGER_MAX for GTFS schedule offsets (up to
# the following service day) when SQL derives absolute-time delays.
MAX_ABSOLUTE_STOP_TIME_OFFSET_SECONDS = 2_000_000_000


def _trip_schedule_relationship(value: int) -> TripScheduleRelationship:
    return _TRIP_SCHEDULE_RELATIONSHIPS.get(
        value,
        TripScheduleRelationship.UNKNOWN,
    )


def _stop_schedule_relationship(value: int) -> StopScheduleRelationship:
    return _STOP_SCHEDULE_RELATIONSHIPS.get(
        value,
        StopScheduleRelationship.UNKNOWN,
    )


def _unknown_enum_values(message: Message, field_name: str) -> tuple[int, ...]:
    field_number = message.DESCRIPTOR.fields_by_name[field_name].number
    return tuple(
        int(field.data)
        for field in UnknownFieldSet(message)
        if field.field_number == field_number and field.wire_type == 0
    )


def _trip_schedule_relationship_from_descriptor(
    descriptor: gtfs_realtime_pb2.TripDescriptor,
) -> TripScheduleRelationship:
    unknown_values = _unknown_enum_values(descriptor, "schedule_relationship")
    if unknown_values:
        return _CURRENT_TRIP_RELATIONSHIPS_MISSING_FROM_BINDING.get(
            unknown_values[-1],
            TripScheduleRelationship.UNKNOWN,
        )
    return _trip_schedule_relationship(descriptor.schedule_relationship)


def _stop_schedule_relationship_from_update(
    update: gtfs_realtime_pb2.TripUpdate.StopTimeUpdate,
) -> StopScheduleRelationship:
    if _unknown_enum_values(update, "schedule_relationship"):
        return StopScheduleRelationship.UNKNOWN
    return _stop_schedule_relationship(update.schedule_relationship)


def _optional_integer(message: object, field_name: str) -> int | None:
    if not message.HasField(field_name):
        return None
    return getattr(message, field_name)


class InvalidGtfsRealtimeTimestamp(ValueError):
    """An upstream Unix timestamp cannot be represented by the application."""


class InvalidGtfsRealtimeRecord(ValueError):
    """An upstream value cannot be represented by the PostGIS estimator."""


def timestamp_as_utc(value: int | None) -> datetime | None:
    if value is None:
        return None
    if type(value) is not int:
        raise InvalidGtfsRealtimeTimestamp("GTFS-RT timestamp must be an integer")
    try:
        return datetime.fromtimestamp(value, UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise InvalidGtfsRealtimeTimestamp(
            f"GTFS-RT timestamp is outside the supported datetime range: {value}"
        ) from error


def _optional_timestamp(message: object, field_name: str) -> int | None:
    value = _optional_integer(message, field_name)
    timestamp_as_utc(value)
    return value


def _service_day_start_seconds(service_date: date) -> int:
    return int(
        datetime(
            service_date.year,
            service_date.month,
            service_date.day,
            tzinfo=UTC,
        ).timestamp()
    )


def _stop_time_timestamp_is_safe(value: int, service_date: date | None) -> bool:
    return service_date is None or abs(
        value - _service_day_start_seconds(service_date)
    ) <= MAX_ABSOLUTE_STOP_TIME_OFFSET_SECONDS


def _optional_stop_timestamp(
    message: object,
    field_name: str,
    service_date: date | None,
) -> int | None:
    value = _optional_timestamp(message, field_name)
    if value is not None and not _stop_time_timestamp_is_safe(value, service_date):
        return None
    return value


def validate_snapshot_timestamps(snapshot: GtfsRealtimeSnapshot) -> None:
    """Also guard normalized snapshots supplied by non-Protobuf source ports."""
    timestamp_as_utc(snapshot.feed_timestamp)
    for update in snapshot.trip_updates:
        timestamp_as_utc(update.trip_update_timestamp)
        for stop in update.stop_time_updates:
            if stop.stop_sequence is not None and (
                type(stop.stop_sequence) is not int
                or not 0 <= stop.stop_sequence <= MAX_STOP_SEQUENCE
            ):
                raise InvalidGtfsRealtimeRecord(
                    "GTFS-RT stop_sequence is outside PostgreSQL INTEGER range"
                )
            for value in (stop.arrival_time, stop.departure_time):
                timestamp_as_utc(value)
                if value is not None and not _stop_time_timestamp_is_safe(
                    value, update.service_date
                ):
                    raise InvalidGtfsRealtimeTimestamp(
                        "GTFS-RT stop time is outside the safe service-day range"
                    )


def _is_deleted(entity: gtfs_realtime_pb2.FeedEntity) -> bool:
    return entity.HasField("is_deleted") and entity.is_deleted


def _optional_text(message: object, field_name: str) -> str | None:
    if not message.HasField(field_name):
        return None
    value = getattr(message, field_name)
    return value or None


def _service_date_from_descriptor(
    descriptor: gtfs_realtime_pb2.TripDescriptor,
) -> date | None:
    start_date = _optional_text(descriptor, "start_date")
    if start_date is None:
        return None
    try:
        return datetime.strptime(start_date, "%Y%m%d").date()
    except ValueError:
        return None


def _normalize_stop_time_update(
    protobuf_update: gtfs_realtime_pb2.TripUpdate.StopTimeUpdate,
    service_date: date | None,
) -> StopTimeUpdate | None:
    stop_sequence = _optional_integer(protobuf_update, "stop_sequence")
    if stop_sequence is not None and not 0 <= stop_sequence <= MAX_STOP_SEQUENCE:
        stop_sequence = None
    stop_id = protobuf_update.stop_id if protobuf_update.HasField("stop_id") else None
    if stop_sequence is None and stop_id is None:
        return None

    arrival = protobuf_update.arrival if protobuf_update.HasField("arrival") else None
    departure = (
        protobuf_update.departure if protobuf_update.HasField("departure") else None
    )
    return StopTimeUpdate(
        stop_sequence=stop_sequence,
        stop_id=stop_id,
        arrival_time=None
        if arrival is None
        else _optional_stop_timestamp(arrival, "time", service_date),
        arrival_delay_seconds=None
        if arrival is None
        else _optional_integer(arrival, "delay"),
        departure_time=None
        if departure is None
        else _optional_stop_timestamp(departure, "time", service_date),
        departure_delay_seconds=None
        if departure is None
        else _optional_integer(departure, "delay"),
        schedule_relationship=_stop_schedule_relationship_from_update(protobuf_update),
    )


def trip_updates_from_feed(
    feed: gtfs_realtime_pb2.FeedMessage,
) -> tuple[TripUpdate, ...]:
    """Preserve identified TripUpdates and their GTFS-RT service states."""
    normalized: list[TripUpdate] = []
    for entity in feed.entity:
        if (
            _is_deleted(entity)
            or not entity.HasField("trip_update")
            or not entity.HasField("id")
        ):
            continue

        protobuf_update = entity.trip_update
        descriptor = protobuf_update.trip
        schedule_relationship = _trip_schedule_relationship_from_descriptor(descriptor)
        trip_id = _optional_text(descriptor, "trip_id")
        route_id = _optional_text(descriptor, "route_id")
        service_date = _service_date_from_descriptor(descriptor)
        if schedule_relationship is TripScheduleRelationship.SCHEDULED and (
            trip_id is None or route_id is None or service_date is None
        ):
            continue

        stop_time_updates = tuple(
            update
            for stop_update in protobuf_update.stop_time_update
            if (
                (update := _normalize_stop_time_update(stop_update, service_date))
                is not None
            )
        )
        normalized.append(
            TripUpdate(
                entity_id=entity.id,
                trip_id=trip_id,
                route_id=route_id,
                service_date=service_date,
                trip_update_timestamp=_optional_timestamp(protobuf_update, "timestamp"),
                stop_time_updates=stop_time_updates,
                schedule_relationship=schedule_relationship,
            )
        )

    return tuple(normalized)


def snapshot_from_feed(
    feed: gtfs_realtime_pb2.FeedMessage,
) -> GtfsRealtimeSnapshot:
    """Normalize only authoritative full feeds; deltas need a reconciler."""
    if feed.header.incrementality != gtfs_realtime_pb2.FeedHeader.FULL_DATASET or any(
        field.field_number
        == feed.header.DESCRIPTOR.fields_by_name["incrementality"].number
        for field in UnknownFieldSet(feed.header)
    ):
        # Proto2 returns the default FULL_DATASET for an unknown wire enum.
        raise ValueError("only GTFS-RT FULL_DATASET incrementality is supported")
    return GtfsRealtimeSnapshot(
        feed_timestamp=_optional_timestamp(feed.header, "timestamp"),
        trip_updates=trip_updates_from_feed(feed),
        deleted_entities=tuple(
            DeletedFeedEntity(entity_id=entity.id)
            for entity in feed.entity
            if entity.HasField("id") and _is_deleted(entity)
        ),
    )
