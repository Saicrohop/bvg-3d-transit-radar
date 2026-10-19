import asyncio

import pytest
from google.transit import gtfs_realtime_pb2
from test_gtfs_realtime_source import FakeResponse, FakeSession, protobuf_empty_feed

from bvg_radar.realtime.normalization import snapshot_from_feed
from bvg_radar.realtime.source import AiohttpGtfsRealtimeSource, GtfsRealtimeFetchError


def feed_with_incrementality(mode):
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    if mode == "differential":
        feed.header.incrementality = gtfs_realtime_pb2.FeedHeader.DIFFERENTIAL
    elif mode == "unknown":
        feed.header.MergeFromString(b"\x10\x63")  # unknown enum value 99 for field 2
    elif mode == "full_with_unknown":
        feed.header.incrementality = gtfs_realtime_pb2.FeedHeader.FULL_DATASET
        feed.header.MergeFromString(b"\x10\x63")
    elif mode == "malformed_wire":
        feed.header.MergeFromString(
            b"\x12\x01x"
        )  # field 2 encoded as a string, not enum
    elif mode == "full":
        feed.header.incrementality = gtfs_realtime_pb2.FeedHeader.FULL_DATASET
    return feed


@pytest.mark.parametrize(
    "mode", ["differential", "unknown", "full_with_unknown", "malformed_wire"]
)
def test_snapshot_normalization_rejects_every_unsupported_incrementality(mode):
    feed = feed_with_incrementality(mode)
    assert feed.IsInitialized()
    with pytest.raises(ValueError, match="FULL_DATASET"):
        snapshot_from_feed(feed)


@pytest.mark.parametrize(
    "mode", ["differential", "unknown", "full_with_unknown", "malformed_wire"]
)
def test_source_does_not_advance_etag_for_unsupported_incrementality(mode):
    session = FakeSession(
        [
            FakeResponse(
                200, feed_with_incrementality(mode).SerializeToString(), etag='"unsafe"'
            ),
            FakeResponse(200, protobuf_empty_feed(), etag='"safe"'),
        ]
    )
    source = AiohttpGtfsRealtimeSource(session, "https://example.test/feed")
    with pytest.raises(GtfsRealtimeFetchError):
        asyncio.run(source.fetch())
    recovered = asyncio.run(source.fetch())
    assert recovered.snapshot.trip_updates == ()
    assert "If-None-Match" not in session.calls[-1][1]


@pytest.mark.parametrize("mode", ["omitted", "full"])
def test_snapshot_normalization_accepts_full_dataset_and_default_full(mode):
    assert snapshot_from_feed(feed_with_incrementality(mode)).trip_updates == ()
