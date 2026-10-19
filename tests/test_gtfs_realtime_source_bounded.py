import asyncio

import pytest
from test_gtfs_realtime_source import FakeResponse, FakeSession, protobuf_empty_feed

from bvg_radar.realtime.source import AiohttpGtfsRealtimeSource, GtfsRealtimeFetchError


class ChunkedResponse(FakeResponse):
    def __init__(self, chunks, etag='"stream"'):
        super().__init__(200, b"", etag=etag)
        self.content = self
        self.chunks = chunks
        self.chunks_consumed = 0
        self.exited = False

    async def read(self):
        raise AssertionError("production polling must never use an unbounded read")

    async def iter_chunked(self, chunk_size):
        assert chunk_size <= 1024 * 1024
        for chunk in self.chunks:
            self.chunks_consumed += 1
            yield chunk

    async def __aexit__(self, *_args):
        self.exited = True


def test_source_streams_protobuf_without_unbounded_response_read():
    payload = protobuf_empty_feed()
    response = ChunkedResponse([payload[:3], payload[3:]])
    source = AiohttpGtfsRealtimeSource(
        FakeSession([response]), "https://example.test/feed"
    )
    result = asyncio.run(source.fetch())
    assert result.snapshot.trip_updates == ()
    assert response.chunks_consumed == 2
    assert response.exited


def test_source_rejects_oversized_stream_before_parse_without_advancing_etag():
    payload = protobuf_empty_feed()
    overflow = ChunkedResponse([payload, b"x", b"not-consumed"], etag='"overflow"')
    overflow.headers["Content-Length"] = "1"  # never trust a compressed/incorrect hint
    exact = ChunkedResponse([payload])
    session = FakeSession([overflow, exact])
    source = AiohttpGtfsRealtimeSource(
        session, "https://example.test/feed", max_bytes=len(payload)
    )
    with pytest.raises(GtfsRealtimeFetchError, match="exceeds"):
        asyncio.run(source.fetch())
    assert overflow.chunks_consumed == 2
    assert overflow.exited
    recovered = asyncio.run(source.fetch())
    assert recovered.snapshot.trip_updates == ()
    assert "If-None-Match" not in session.calls[-1][1]


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, float("nan"), float("inf")])
def test_source_requires_positive_integer_payload_limit(limit):
    with pytest.raises(ValueError, match="max_bytes"):
        AiohttpGtfsRealtimeSource(
            FakeSession([]), "https://example.test/feed", max_bytes=limit
        )


def test_source_rejects_empty_stream():
    response = ChunkedResponse([])
    source = AiohttpGtfsRealtimeSource(
        FakeSession([response]), "https://example.test/feed"
    )
    with pytest.raises(GtfsRealtimeFetchError, match="empty"):
        asyncio.run(source.fetch())
    assert response.exited
