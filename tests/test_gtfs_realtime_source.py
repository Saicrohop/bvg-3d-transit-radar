import asyncio
from datetime import date

import pytest
from google.transit import gtfs_realtime_pb2

from bvg_radar.realtime.models import (
    GtfsRealtimeFetchResult,
    GtfsRealtimeFetchStatus,
    GtfsRealtimeSnapshot,
)
from bvg_radar.realtime.source import AiohttpGtfsRealtimeSource


class FakeResponse:
    def __init__(
        self,
        status: int,
        payload: bytes = b"",
        etag: str | None = None,
        content_type: str = "application/protobuf",
    ) -> None:
        self.status = status
        self._payload = payload
        self.headers = {"Content-Type": content_type}
        if etag is not None:
            self.headers["ETag"] = etag

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *_arguments: object) -> None:
        return None

    async def read(self) -> bytes:
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, *, headers: dict[str, str]) -> FakeResponse:
        self.calls.append((url, headers))
        return self._responses.pop(0)


def protobuf_trip_update() -> bytes:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = 1_784_457_600
    entity = feed.entity.add()
    entity.id = "entity-42"
    entity.trip_update.trip.trip_id = "trip-42"
    entity.trip_update.trip.route_id = "route-7"
    entity.trip_update.trip.start_date = "20260719"
    return feed.SerializeToString()


def protobuf_empty_feed() -> bytes:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = 1_784_457_600
    return feed.SerializeToString()


def protobuf_uninitialized_feed() -> bytes:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.entity.add().id = "entity-without-required-header"
    return feed.SerializePartialToString()


@pytest.mark.parametrize(
    ("status", "snapshot"),
    [
        (GtfsRealtimeFetchStatus.UPDATED, None),
        (
            GtfsRealtimeFetchStatus.NOT_MODIFIED,
            GtfsRealtimeSnapshot(feed_timestamp=None, trip_updates=()),
        ),
    ],
)
def test_fetch_result_rejects_contradictory_status_and_snapshot(
    status: GtfsRealtimeFetchStatus,
    snapshot: GtfsRealtimeSnapshot | None,
) -> None:
    with pytest.raises(ValueError, match="snapshot"):
        GtfsRealtimeFetchResult(status=status, snapshot=snapshot)


def test_source_distinguishes_valid_empty_snapshot_from_not_modified() -> None:
    source = AiohttpGtfsRealtimeSource(
        session=FakeSession(
            [
                FakeResponse(200, protobuf_empty_feed(), etag='"empty"'),
                FakeResponse(304),
            ]
        ),
        url="https://production.gtfsrt.vbb.de/data",
    )

    updated = asyncio.run(source.fetch())
    not_modified = asyncio.run(source.fetch())

    assert updated.status is GtfsRealtimeFetchStatus.UPDATED
    assert updated.snapshot is not None
    assert updated.snapshot.feed_timestamp == 1_784_457_600
    assert updated.snapshot.trip_updates == ()
    assert not_modified.status is GtfsRealtimeFetchStatus.NOT_MODIFIED
    assert not_modified.snapshot is None


def test_source_does_not_reuse_etag_from_an_invalid_protobuf_payload() -> None:
    session = FakeSession(
        [
            FakeResponse(200, b"\xff", etag='"invalid"'),
            FakeResponse(200, protobuf_trip_update(), etag='"valid"'),
        ]
    )
    source = AiohttpGtfsRealtimeSource(
        session=session,
        url="https://production.gtfsrt.vbb.de/data",
    )

    with pytest.raises(RuntimeError, match="valid Protobuf"):
        asyncio.run(source.fetch())
    recovered = asyncio.run(source.fetch())

    assert recovered.status is GtfsRealtimeFetchStatus.UPDATED
    assert session.calls[1][1] == {"User-Agent": "bvg-3d-radar/1.0"}


def test_source_rejects_uninitialized_protobuf_without_advancing_etag() -> None:
    session = FakeSession(
        [
            FakeResponse(200, protobuf_uninitialized_feed(), etag='"incomplete"'),
            FakeResponse(200, protobuf_trip_update(), etag='"valid"'),
        ]
    )
    source = AiohttpGtfsRealtimeSource(
        session=session,
        url="https://production.gtfsrt.vbb.de/data",
    )

    with pytest.raises(RuntimeError, match="valid Protobuf"):
        asyncio.run(source.fetch())
    recovered = asyncio.run(source.fetch())

    assert recovered.status is GtfsRealtimeFetchStatus.UPDATED
    assert session.calls[1][1] == {"User-Agent": "bvg-3d-radar/1.0"}


def test_source_sends_user_agent_and_reuses_etag_without_forcing_accept() -> None:
    session = FakeSession(
        [
            FakeResponse(200, protobuf_trip_update(), etag='"first"'),
            FakeResponse(304),
        ]
    )
    source = AiohttpGtfsRealtimeSource(
        session=session,
        url="https://production.gtfsrt.vbb.de/data",
    )

    first = asyncio.run(source.fetch())
    second = asyncio.run(source.fetch())

    assert first.snapshot is not None
    assert first.snapshot.trip_updates[0].trip_id == "trip-42"
    assert first.snapshot.trip_updates[0].service_date == date(2026, 7, 19)
    assert second.status is GtfsRealtimeFetchStatus.NOT_MODIFIED
    assert session.calls == [
        (
            "https://production.gtfsrt.vbb.de/data",
            {"User-Agent": "bvg-3d-radar/1.0"},
        ),
        (
            "https://production.gtfsrt.vbb.de/data",
            {
                "User-Agent": "bvg-3d-radar/1.0",
                "If-None-Match": '"first"',
            },
        ),
    ]


def test_source_clears_a_stale_etag_after_valid_response_without_etag() -> None:
    session = FakeSession(
        [
            FakeResponse(200, protobuf_trip_update(), etag='"first"'),
            FakeResponse(200, protobuf_trip_update()),
            FakeResponse(200, protobuf_trip_update(), etag='"third"'),
        ]
    )
    source = AiohttpGtfsRealtimeSource(
        session=session,
        url="https://production.gtfsrt.vbb.de/data",
    )

    asyncio.run(source.fetch())
    asyncio.run(source.fetch())
    asyncio.run(source.fetch())

    assert session.calls[1][1]["If-None-Match"] == '"first"'
    assert session.calls[2][1] == {"User-Agent": "bvg-3d-radar/1.0"}


def test_source_rejects_html_despite_a_successful_http_status() -> None:
    source = AiohttpGtfsRealtimeSource(
        session=FakeSession(
            [
                FakeResponse(
                    200,
                    b"<html>not protobuf</html>",
                    content_type="text/html",
                )
            ]
        ),
        url="https://production.gtfsrt.vbb.de/data",
    )

    with pytest.raises(RuntimeError, match="Content-Type"):
        asyncio.run(source.fetch())


def test_source_rejects_an_empty_protobuf_response() -> None:
    source = AiohttpGtfsRealtimeSource(
        session=FakeSession([FakeResponse(200)]),
        url="https://production.gtfsrt.vbb.de/data",
    )

    with pytest.raises(RuntimeError, match="empty"):
        asyncio.run(source.fetch())
