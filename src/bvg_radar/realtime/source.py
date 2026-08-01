from typing import Protocol

from google.transit import gtfs_realtime_pb2

from .models import TripUpdate
from .normalization import trip_updates_from_feed

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


class _HttpResponse(Protocol):
    status: int
    headers: dict[str, str]

    async def __aenter__(self) -> "_HttpResponse": ...

    async def __aexit__(self, *_arguments: object) -> None: ...

    async def read(self) -> bytes: ...


class _HttpSession(Protocol):
    def get(self, url: str, *, headers: dict[str, str]) -> _HttpResponse: ...


class AiohttpGtfsRealtimeSource:
    """Fetches and decodes VBB GTFS-RT while reusing a caller-owned session."""

    def __init__(self, session: _HttpSession, url: str) -> None:
        self._session = session
        self._url = url
        self._etag: str | None = None

    async def fetch_trip_updates(self) -> tuple[TripUpdate, ...]:
        headers = {} if self._etag is None else {"If-None-Match": self._etag}
        async with self._session.get(self._url, headers=headers) as response:
            if response.status == 304:
                return ()
            if response.status != 200:
                raise GtfsRealtimeFetchError(
                    f"GTFS-RT request failed with HTTP {response.status}"
                )
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
            if content_type.strip().lower() not in SUPPORTED_PROTOBUF_MEDIA_TYPES:
                raise GtfsRealtimeFetchError(
                    f"Unexpected GTFS-RT Content-Type: {content_type or '<missing>'}"
                )
            payload = await response.read()
            if not payload:
                raise GtfsRealtimeFetchError("GTFS-RT payload is empty")
            self._etag = response.headers.get("ETag", self._etag)

        feed = gtfs_realtime_pb2.FeedMessage()
        try:
            feed.ParseFromString(payload)
        except Exception as error:
            raise GtfsRealtimeFetchError("GTFS-RT payload is not valid Protobuf") from error
        return trip_updates_from_feed(feed)
