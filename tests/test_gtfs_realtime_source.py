import asyncio
from datetime import date

import pytest
from google.transit import gtfs_realtime_pb2

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


def test_source_reuses_etag_without_forcing_an_incompatible_accept_header() -> None:
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

    first = asyncio.run(source.fetch_trip_updates())
    second = asyncio.run(source.fetch_trip_updates())

    assert first[0].trip_id == "trip-42"
    assert first[0].service_date == date(2026, 7, 19)
    assert second == ()
    assert session.calls == [
        ("https://production.gtfsrt.vbb.de/data", {}),
        ("https://production.gtfsrt.vbb.de/data", {"If-None-Match": '"first"'}),
    ]


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
        asyncio.run(source.fetch_trip_updates())


def test_source_rejects_an_empty_protobuf_response() -> None:
    source = AiohttpGtfsRealtimeSource(
        session=FakeSession([FakeResponse(200)]),
        url="https://production.gtfsrt.vbb.de/data",
    )

    with pytest.raises(RuntimeError, match="empty"):
        asyncio.run(source.fetch_trip_updates())
