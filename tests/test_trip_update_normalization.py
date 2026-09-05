from datetime import date

import pytest
from google.transit import gtfs_realtime_pb2

from bvg_radar.realtime.models import (
    DeletedFeedEntity,
    StopScheduleRelationship,
    StopTimeUpdate,
    TripScheduleRelationship,
)
from bvg_radar.realtime.normalization import (
    _stop_schedule_relationship,
    _trip_schedule_relationship,
    snapshot_from_feed,
    trip_updates_from_feed,
)


def test_maps_future_schedule_relationships_to_explicit_unknown_state() -> None:
    assert _trip_schedule_relationship(999) is TripScheduleRelationship.UNKNOWN
    assert _stop_schedule_relationship(999) is StopScheduleRelationship.UNKNOWN


def test_preserves_unknown_schedule_relationships_from_proto2_wire() -> None:
    feed = gtfs_realtime_pb2.FeedMessage()
    entity = feed.entity.add()
    entity.id = "entity-future-state"
    descriptor = entity.trip_update.trip
    descriptor.trip_id = "trip-42"
    descriptor.route_id = "route-7"
    descriptor.start_date = "20260719"
    descriptor.MergeFromString(b"\x20\x63")  # field 4, enum value 99
    stop_update = entity.trip_update.stop_time_update.add()
    stop_update.stop_sequence = 3
    stop_update.MergeFromString(b"\x28\x63")  # field 5, enum value 99

    snapshot = snapshot_from_feed(feed)

    update = snapshot.trip_updates[0]
    assert update.schedule_relationship is TripScheduleRelationship.UNKNOWN
    assert (
        update.stop_time_updates[0].schedule_relationship
        is StopScheduleRelationship.UNKNOWN
    )


@pytest.mark.parametrize(
    ("wire_value", "expected_relationship"),
    [
        (7, TripScheduleRelationship.DELETED),
        (8, TripScheduleRelationship.NEW),
    ],
)
def test_recognizes_current_trip_states_missing_from_installed_binding(
    wire_value: int,
    expected_relationship: TripScheduleRelationship,
) -> None:
    feed = gtfs_realtime_pb2.FeedMessage()
    entity = feed.entity.add()
    entity.id = "entity-current-state"
    descriptor = entity.trip_update.trip
    descriptor.trip_id = "trip-42"
    descriptor.MergeFromString(bytes((0x20, wire_value)))

    snapshot = snapshot_from_feed(feed)

    assert snapshot.trip_updates[0].schedule_relationship is expected_relationship


def test_preserves_deleted_feed_entity_identity() -> None:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = 1_784_457_500
    entity = feed.entity.add()
    entity.id = "entity-removed"
    entity.is_deleted = True

    snapshot = snapshot_from_feed(feed)

    assert snapshot.deleted_entities == (
        DeletedFeedEntity(entity_id="entity-removed"),
    )
    assert snapshot.trip_updates == ()


def test_deleted_entity_takes_precedence_over_embedded_trip_update() -> None:
    feed = gtfs_realtime_pb2.FeedMessage()
    entity = feed.entity.add()
    entity.id = "entity-removed"
    entity.is_deleted = True
    descriptor = entity.trip_update.trip
    descriptor.trip_id = "trip-42"
    descriptor.route_id = "route-7"
    descriptor.start_date = "20260719"

    snapshot = snapshot_from_feed(feed)

    assert snapshot.deleted_entities == (
        DeletedFeedEntity(entity_id="entity-removed"),
    )
    assert snapshot.trip_updates == ()


def test_preserves_feed_and_trip_update_timestamps_separately() -> None:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = 1_784_457_500
    entity = feed.entity.add()
    entity.id = "entity-42"
    entity.trip_update.trip.trip_id = "trip-42"
    entity.trip_update.trip.route_id = "route-7"
    entity.trip_update.trip.start_date = "20260719"
    entity.trip_update.timestamp = 1_784_457_600

    snapshot = snapshot_from_feed(feed)

    assert snapshot.feed_timestamp == 1_784_457_500
    assert snapshot.trip_updates[0].trip_update_timestamp == 1_784_457_600


@pytest.mark.parametrize(
    ("protobuf_relationship", "expected_relationship"),
    [
        (
            gtfs_realtime_pb2.TripDescriptor.SCHEDULED,
            TripScheduleRelationship.SCHEDULED,
        ),
        (gtfs_realtime_pb2.TripDescriptor.ADDED, TripScheduleRelationship.ADDED),
        (
            gtfs_realtime_pb2.TripDescriptor.UNSCHEDULED,
            TripScheduleRelationship.UNSCHEDULED,
        ),
        (
            gtfs_realtime_pb2.TripDescriptor.CANCELED,
            TripScheduleRelationship.CANCELED,
        ),
        (
            gtfs_realtime_pb2.TripDescriptor.REPLACEMENT,
            TripScheduleRelationship.REPLACEMENT,
        ),
        (
            gtfs_realtime_pb2.TripDescriptor.DUPLICATED,
            TripScheduleRelationship.DUPLICATED,
        ),
    ],
)
def test_preserves_trip_schedule_relationship(
    protobuf_relationship: int,
    expected_relationship: TripScheduleRelationship,
) -> None:
    feed = gtfs_realtime_pb2.FeedMessage()
    entity = feed.entity.add()
    entity.id = "entity-42"
    descriptor = entity.trip_update.trip
    descriptor.trip_id = "trip-42"
    descriptor.route_id = "route-7"
    descriptor.start_date = "20260719"
    descriptor.schedule_relationship = protobuf_relationship

    snapshot = snapshot_from_feed(feed)

    assert snapshot.trip_updates[0].schedule_relationship is expected_relationship


def test_preserves_canceled_trip_without_static_interpolation_fields() -> None:
    feed = gtfs_realtime_pb2.FeedMessage()
    entity = feed.entity.add()
    entity.id = "entity-canceled"
    descriptor = entity.trip_update.trip
    descriptor.trip_id = "trip-canceled"
    descriptor.schedule_relationship = gtfs_realtime_pb2.TripDescriptor.CANCELED

    snapshot = snapshot_from_feed(feed)

    assert len(snapshot.trip_updates) == 1
    canceled = snapshot.trip_updates[0]
    assert canceled.entity_id == "entity-canceled"
    assert canceled.trip_id == "trip-canceled"
    assert canceled.route_id is None
    assert canceled.service_date is None
    assert canceled.schedule_relationship is TripScheduleRelationship.CANCELED


@pytest.mark.parametrize(
    ("protobuf_relationship", "expected_relationship"),
    [
        (
            gtfs_realtime_pb2.TripUpdate.StopTimeUpdate.SCHEDULED,
            StopScheduleRelationship.SCHEDULED,
        ),
        (
            gtfs_realtime_pb2.TripUpdate.StopTimeUpdate.SKIPPED,
            StopScheduleRelationship.SKIPPED,
        ),
        (
            gtfs_realtime_pb2.TripUpdate.StopTimeUpdate.NO_DATA,
            StopScheduleRelationship.NO_DATA,
        ),
        (
            gtfs_realtime_pb2.TripUpdate.StopTimeUpdate.UNSCHEDULED,
            StopScheduleRelationship.UNSCHEDULED,
        ),
    ],
)
def test_preserves_stop_schedule_relationship(
    protobuf_relationship: int,
    expected_relationship: StopScheduleRelationship,
) -> None:
    feed = gtfs_realtime_pb2.FeedMessage()
    entity = feed.entity.add()
    entity.id = "entity-42"
    descriptor = entity.trip_update.trip
    descriptor.trip_id = "trip-42"
    descriptor.route_id = "route-7"
    descriptor.start_date = "20260719"
    stop_update = entity.trip_update.stop_time_update.add()
    stop_update.stop_sequence = 3
    stop_update.schedule_relationship = protobuf_relationship

    snapshot = snapshot_from_feed(feed)

    assert (
        snapshot.trip_updates[0].stop_time_updates[0].schedule_relationship
        is expected_relationship
    )


def test_skipped_stop_does_not_supply_timing_evidence_to_estimator() -> None:
    feed = gtfs_realtime_pb2.FeedMessage()
    entity = feed.entity.add()
    entity.id = "entity-42"
    descriptor = entity.trip_update.trip
    descriptor.trip_id = "trip-42"
    descriptor.route_id = "route-7"
    descriptor.start_date = "20260719"
    stop_update = entity.trip_update.stop_time_update.add()
    stop_update.stop_sequence = 3
    stop_update.stop_id = "stop-3"
    stop_update.schedule_relationship = (
        gtfs_realtime_pb2.TripUpdate.StopTimeUpdate.SKIPPED
    )
    stop_update.arrival.time = 1_784_457_900
    stop_update.arrival.delay = 90
    stop_update.departure.time = 1_784_457_960
    stop_update.departure.delay = 60

    normalized = snapshot_from_feed(feed).trip_updates[0].stop_time_updates[0]

    assert normalized.arrival_time == 1_784_457_900
    assert normalized.departure_time == 1_784_457_960
    assert normalized.to_estimator_payload() == {
        "stop_sequence": 3,
        "stop_id": "stop-3",
    }


def test_no_data_stop_does_not_supply_timing_evidence_to_estimator() -> None:
    update = StopTimeUpdate(
        stop_sequence=3,
        stop_id="stop-3",
        arrival_time=1_784_457_900,
        arrival_delay_seconds=90,
        departure_time=1_784_457_960,
        departure_delay_seconds=60,
        schedule_relationship=StopScheduleRelationship.NO_DATA,
    )

    assert update.to_estimator_payload() == {
        "stop_sequence": 3,
        "stop_id": "stop-3",
    }


def test_normalizes_trip_update_with_absolute_times_and_delays() -> None:
    feed = gtfs_realtime_pb2.FeedMessage()
    entity = feed.entity.add()
    entity.id = "entity-42"
    update = entity.trip_update
    update.trip.trip_id = "trip-42"
    update.trip.route_id = "route-7"
    update.trip.start_date = "20260719"
    update.timestamp = 1_784_457_600

    stop_update = update.stop_time_update.add()
    stop_update.stop_sequence = 3
    stop_update.stop_id = "stop-3"
    stop_update.arrival.time = 1_784_457_900
    stop_update.arrival.delay = 90
    stop_update.departure.delay = 60

    normalized = trip_updates_from_feed(feed)

    assert len(normalized) == 1
    result = normalized[0]
    assert result.entity_id == "entity-42"
    assert result.trip_id == "trip-42"
    assert result.route_id == "route-7"
    assert result.service_date == date(2026, 7, 19)
    assert result.trip_update_timestamp == 1_784_457_600
    assert result.stop_time_updates[0].stop_sequence == 3
    assert result.stop_time_updates[0].arrival_time == 1_784_457_900
    assert result.stop_time_updates[0].arrival_delay_seconds == 90
    assert result.stop_time_updates[0].departure_time is None
    assert result.stop_time_updates[0].departure_delay_seconds == 60


def test_ignores_trip_update_without_static_trip_identity() -> None:
    feed = gtfs_realtime_pb2.FeedMessage()
    entity = feed.entity.add()
    entity.trip_update.trip.route_id = "route-7"
    entity.trip_update.trip.start_date = "20260719"

    assert trip_updates_from_feed(feed) == ()
