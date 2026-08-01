from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


GTFS_ROUTE_METADATA_SQL = """
SELECT
    route.route_type,
    route.route_short_name
FROM gtfs.trips AS trip
JOIN gtfs.routes AS route ON route.route_id = trip.route_id
WHERE trip.trip_id = $1::TEXT;
"""


@dataclass(frozen=True, slots=True)
class RouteMetadata:
    route_type: int
    route_short_name: str | None


class _QueryConnection(Protocol):
    async def fetchrow(
        self, query: str, *arguments: object
    ) -> Mapping[str, object] | None: ...


class GtfsRouteMetadataLookup:
    """Read backend-only route metadata from static VBB GTFS tables."""

    def __init__(self, connection: _QueryConnection) -> None:
        self._connection = connection

    async def find_by_trip_id(self, trip_id: str) -> RouteMetadata | None:
        row = await self._connection.fetchrow(GTFS_ROUTE_METADATA_SQL, trip_id)
        if row is None:
            return None

        route_short_name = row["route_short_name"]
        return RouteMetadata(
            route_type=int(row["route_type"]),
            route_short_name=(
                None if route_short_name is None else str(route_short_name)
            ),
        )
