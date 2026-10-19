from collections.abc import AsyncIterator
from typing import Protocol

from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2

from .models import GtfsRealtimeFetchResult, GtfsRealtimeFetchStatus
from .normalization import snapshot_from_feed

MAX_GTFS_REALTIME_BYTES = 64 * 1024 * 1024

SUPPORTED_PROTOBUF_MEDIA_TYPES = frozenset(
    {
        "application/protobuf",
        "application/x-protobuf",
        "application/octet-stream",
        "application/vnd.google.protobuf",
    }
)


class GtfsRealtimeFetchError(RuntimeError):
    """The upstream feed could not be retrieved as a usable Protobuf payload."""


class _HttpContent(Protocol):
    def iter_chunked(self, chunk_size: int) -> AsyncIterator[bytes]: ...


class _HttpResponse(Protocol):
    status: int
    headers: dict[str, str]
    content: _HttpContent

    async def __aenter__(self) -> "_HttpResponse": ...

    async def __aexit__(self, *_arguments: object) -> None: ...


class _HttpSession(Protocol):
    def get(self, url: str, *, headers: dict[str, str]) -> _HttpResponse: ...


class AiohttpGtfsRealtimeSource:
    """Fetches and decodes VBB GTFS-RT while reusing a caller-owned session."""

    def __init__(
        self,
        session: _HttpSession,
        url: str,
        *,
        max_bytes: int = MAX_GTFS_REALTIME_BYTES,
    ) -> None:
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        self._max_bytes = max_bytes
        self._session = session
        self._url = url
        self._etag: str | None = None

    async def fetch(self) -> GtfsRealtimeFetchResult:
        headers = {"User-Agent": "bvg-3d-radar/1.0"}
        if self._etag is not None:
            headers["If-None-Match"] = self._etag
        async with self._session.get(self._url, headers=headers) as response:
            if response.status == 304:
                return GtfsRealtimeFetchResult(
                    status=GtfsRealtimeFetchStatus.NOT_MODIFIED,
                    snapshot=None,
                )
            if response.status != 200:
                raise GtfsRealtimeFetchError(
                    f"GTFS-RT request failed with HTTP {response.status}"
                )
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
            if content_type.strip().lower() not in SUPPORTED_PROTOBUF_MEDIA_TYPES:
                raise GtfsRealtimeFetchError(
                    f"Unexpected GTFS-RT Content-Type: {content_type or '<missing>'}"
                )
            # Same bounded streaming policy as the static-compatibility probe.
            # aiohttp chunks are decoded bytes: compressed Content-Length isn't a cap.
            payload_buffer = bytearray()
            async for chunk in response.content.iter_chunked(1024 * 1024):
                if len(payload_buffer) + len(chunk) > self._max_bytes:
                    raise GtfsRealtimeFetchError(
                        f"GTFS-RT payload exceeds {self._max_bytes} bytes"
                    )
                payload_buffer.extend(chunk)
            payload = bytes(payload_buffer)
            if not payload:
                raise GtfsRealtimeFetchError("GTFS-RT payload is empty")
            response_etag = response.headers.get("ETag")

        feed = gtfs_realtime_pb2.FeedMessage()
        try:
            feed.ParseFromString(payload)
            if not feed.IsInitialized():
                raise ValueError("required GTFS-RT Protobuf fields are missing")
            snapshot = snapshot_from_feed(feed)
        except (DecodeError, ValueError) as error:
            raise GtfsRealtimeFetchError(
                "GTFS-RT payload is not valid Protobuf"
            ) from error
        self._etag = response_etag
        return GtfsRealtimeFetchResult(
            status=GtfsRealtimeFetchStatus.UPDATED,
            snapshot=snapshot,
        )
