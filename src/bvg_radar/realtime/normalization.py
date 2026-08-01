from datetime import datetime

from google.transit import gtfs_realtime_pb2

from .models import StopTimeUpdate, TripUpdate


def _optional_integer(message: object, field_name: str) -> int | None:
    if not message.HasField(field_name):
        return None
    return getattr(message, field_name)


def _normalize_stop_time_update(
    protobuf_update: gtfs_realtime_pb2.TripUpdate.StopTimeUpdate,
) -> StopTimeUpdate | None:
    stop_sequence = _optional_integer(protobuf_update, "stop_sequence")
    stop_id = protobuf_update.stop_id if protobuf_update.HasField("stop_id") else None
    if stop_sequence is None and stop_id is None:
        return None

    arrival = protobuf_update.arrival if protobuf_update.HasField("arrival") else None
    departure = protobuf_update.departure if protobuf_update.HasField("departure") else None
    return StopTimeUpdate(
        stop_sequence=stop_sequence,
        stop_id=stop_id,
        arrival_time=None if arrival is None else _optional_integer(arrival, "time"),
        arrival_delay_seconds=None
        if arrival is None
        else _optional_integer(arrival, "delay"),
        departure_time=None
        if departure is None
        else _optional_integer(departure, "time"),
        departure_delay_seconds=None
        if departure is None
        else _optional_integer(departure, "delay"),
    )


def trip_updates_from_feed(
    feed: gtfs_realtime_pb2.FeedMessage,
) -> tuple[TripUpdate, ...]:
    """Convert only complete, static-GTFS-matchable TripUpdates into domain DTOs."""
    normalized: list[TripUpdate] = []
    for entity in feed.entity:
        if not entity.HasField("trip_update") or not entity.HasField("id"):
            continue

        protobuf_update = entity.trip_update
        descriptor = protobuf_update.trip
        if not (
            descriptor.HasField("trip_id")
            and descriptor.HasField("route_id")
            and descriptor.HasField("start_date")
        ):
            continue

        try:
            service_date = datetime.strptime(descriptor.start_date, "%Y%m%d").date()
        except ValueError:
            continue

        stop_time_updates = tuple(
            update
            for stop_update in protobuf_update.stop_time_update
            if (update := _normalize_stop_time_update(stop_update)) is not None
        )
        normalized.append(
            TripUpdate(
                entity_id=entity.id,
                trip_id=descriptor.trip_id,
                route_id=descriptor.route_id,
                service_date=service_date,
                feed_timestamp=_optional_integer(protobuf_update, "timestamp"),
                stop_time_updates=stop_time_updates,
            )
        )

    return tuple(normalized)
