import asyncio

from bvg_radar.realtime.gtfs_route_metadata import GtfsRouteMetadataLookup


class RecordingConnection:
    def __init__(self) -> None:
        self.arguments: tuple[object, ...] | None = None
        self.query: str | None = None

    async def fetchrow(self, query: str, *arguments: object) -> dict[str, object]:
        self.query = query
        self.arguments = arguments
        return {
            "route_type": 2,
            "route_short_name": "S41",
        }


class MissingRouteConnection:
    async def fetchrow(self, _query: str, *_arguments: object) -> None:
        return None


def test_gtfs_route_metadata_lookup_joins_static_trip_and_route_by_trip_id() -> None:
    connection = RecordingConnection()
    lookup = GtfsRouteMetadataLookup(connection)

    result = asyncio.run(lookup.find_by_trip_id("trip-s41"))

    assert result is not None
    assert result.route_type == 2
    assert result.route_short_name == "S41"
    assert connection.arguments == ("trip-s41",)
    assert connection.query is not None
    assert "FROM gtfs.trips AS trip" in connection.query
    assert "JOIN gtfs.routes AS route ON route.route_id = trip.route_id" in connection.query


def test_gtfs_route_metadata_lookup_returns_none_when_static_trip_is_missing() -> None:
    lookup = GtfsRouteMetadataLookup(MissingRouteConnection())

    result = asyncio.run(lookup.find_by_trip_id("missing-trip"))

    assert result is None
