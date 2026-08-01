from datetime import date

from google.transit import gtfs_realtime_pb2

from bvg_radar.realtime.normalization import trip_updates_from_feed


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
    assert result.feed_timestamp == 1_784_457_600
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
