from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Protocol


ROUTE_LIST_SQL = """
SELECT route_id, route_short_name, route_type
FROM gtfs.routes
ORDER BY route_short_name NULLS LAST, route_id
"""


ROUTE_PATH_SQL = """
WITH route_base AS (
    SELECT route_id, route_short_name, route_type
    FROM gtfs.routes
    WHERE route_id = $1
), route_trips AS (
    SELECT trip.trip_id, trip.shape_id
    FROM gtfs.trips AS trip
    JOIN route_base AS route USING (route_id)
    WHERE trip.shape_id IS NOT NULL
), shape_usage AS (
    SELECT shape_id, count(*)::integer AS trip_count
    FROM route_trips
    GROUP BY shape_id
), selected_shapes AS (
    SELECT shape_id, trip_count
    FROM shape_usage
    ORDER BY trip_count DESC, shape_id
    LIMIT 3
), trip_patterns AS (
    SELECT route_trip.trip_id,
           route_trip.shape_id,
           array_agg(stop_time.stop_id ORDER BY stop_time.stop_sequence) AS stop_pattern
    FROM route_trips AS route_trip
    JOIN selected_shapes AS selected USING (shape_id)
    JOIN gtfs.stop_times AS stop_time USING (trip_id)
    GROUP BY route_trip.trip_id, route_trip.shape_id
), pattern_usage AS (
    SELECT shape_id,
           stop_pattern,
           count(*)::integer AS trip_count,
           min(trip_id) AS representative_trip_id
    FROM trip_patterns
    GROUP BY shape_id, stop_pattern
), representative_trip AS (
    SELECT representative_trip_id
    FROM pattern_usage
    ORDER BY trip_count DESC, shape_id, representative_trip_id
    LIMIT 1
), shape_payload AS (
    SELECT coalesce(
        jsonb_agg(
            jsonb_build_object(
                'shape_id', selected.shape_id,
                'trip_count', selected.trip_count,
                'geojson', extensions.st_asgeojson(shape.geom_4326, 5, 0)::jsonb
            ) ORDER BY selected.trip_count DESC, selected.shape_id
        ),
        '[]'::jsonb
    ) AS shapes
    FROM selected_shapes AS selected
    JOIN gtfs.route_shapes_geom AS shape USING (shape_id)
), stop_payload AS (
    SELECT coalesce(
        jsonb_agg(
            jsonb_build_object(
                'stop_sequence', stop_time.stop_sequence,
                'stop_id', stop.stop_id,
                'stop_name', stop.stop_name,
                'lon', extensions.st_x(stop.geom),
                'lat', extensions.st_y(stop.geom),
                'arrival_time', stop_time.arrival_time
            ) ORDER BY stop_time.stop_sequence
        ),
        '[]'::jsonb
    ) AS stops
    FROM representative_trip AS representative
    JOIN gtfs.stop_times AS stop_time
        ON stop_time.trip_id = representative.representative_trip_id
    JOIN gtfs.stops AS stop USING (stop_id)
    WHERE stop.geom IS NOT NULL
)
SELECT route.route_id,
       route.route_short_name,
       route.route_type,
       shape_payload.shapes,
       stop_payload.stops
FROM route_base AS route
CROSS JOIN shape_payload
CROSS JOIN stop_payload
"""


STOPS_QUERY_SQL = """
WITH envelope AS (
    SELECT extensions.st_makeenvelope($1, $2, $3, $4, 4326) AS geom
), candidate_stops AS MATERIALIZED (
    SELECT stop.stop_id, stop.stop_name, stop.location_type, stop.geom
    FROM gtfs.stops AS stop
    CROSS JOIN envelope
    WHERE stop.geom && envelope.geom
      AND extensions.st_intersects(stop.geom, envelope.geom)
      AND stop.location_type IN (0, 1)
    ORDER BY stop.location_type DESC, stop.stop_name, stop.stop_id
    LIMIT CASE
        WHEN coalesce(array_length($5::text[], 1), 0) = 0 THEN $6
        ELSE NULL::integer
    END
), candidate_modes AS (
    SELECT candidate.stop_id,
           candidate.stop_name,
           candidate.location_type,
           candidate.geom,
           coalesce(stop_modes.modes, ARRAY[]::text[]) AS modes
    FROM candidate_stops AS candidate
    LEFT JOIN LATERAL (
        SELECT array_agg(mode.vehicle_category ORDER BY mode.vehicle_category) AS modes
        FROM gtfs.stop_vehicle_modes AS mode
        WHERE mode.stop_id = candidate.stop_id
    ) AS stop_modes ON true
), matched_stops AS (
    SELECT stop_id, stop_name, location_type, geom, modes
    FROM candidate_modes
    WHERE coalesce(array_length($5::text[], 1), 0) = 0
       OR modes && $5::text[]
    ORDER BY location_type DESC, stop_name, stop_id
    LIMIT $6
)
SELECT stop_id,
       stop_name,
       location_type,
       extensions.st_y(geom) AS lat,
       extensions.st_x(geom) AS lon,
       modes
FROM matched_stops
ORDER BY location_type DESC, stop_name, stop_id
"""


PUNCTUALITY_DAILY_SQL = """
WITH daily_rollups AS (
    SELECT daily.route_id,
           route.route_short_name,
           daily.vehicle_category,
           daily.samples,
           daily.on_time,
           daily.late,
           daily.on_time_ratio,
           daily.mean_delay_seconds
    FROM analytics.route_daily_punctuality AS daily
    LEFT JOIN gtfs.routes AS route USING (route_id)
    WHERE daily.service_day = $1
), qualified AS (
    SELECT *
    FROM daily_rollups
    WHERE samples >= $3
), most_ranked AS (
    SELECT row_number() OVER (
               ORDER BY on_time_ratio DESC,
                        mean_delay_seconds ASC,
                        route_id,
                        vehicle_category
           )::integer AS position,
           qualified.*
    FROM qualified
), least_ranked AS (
    SELECT row_number() OVER (
               ORDER BY on_time_ratio ASC,
                        mean_delay_seconds DESC,
                        route_id,
                        vehicle_category
           )::integer AS position,
           qualified.*
    FROM qualified
), totals AS (
    SELECT count(DISTINCT route_id)::integer AS routes,
           count(*)::integer AS route_categories,
           coalesce(sum(samples), 0)::bigint AS samples,
           coalesce(sum(on_time), 0)::bigint AS on_time,
           coalesce(sum(late), 0)::bigint AS late
    FROM daily_rollups
)
SELECT coalesce(
           (
               SELECT jsonb_agg(
                   jsonb_build_object(
                       'position', position,
                       'route_id', route_id,
                       'route_short_name', route_short_name,
                       'vehicle_category', vehicle_category,
                       'samples', samples,
                       'on_time_ratio', on_time_ratio,
                       'mean_delay_seconds', mean_delay_seconds
                   ) ORDER BY position
               )
               FROM most_ranked
               WHERE position <= $2
           ),
           '[]'::jsonb
       ) AS most_punctual,
       coalesce(
           (
               SELECT jsonb_agg(
                   jsonb_build_object(
                       'position', position,
                       'route_id', route_id,
                       'route_short_name', route_short_name,
                       'vehicle_category', vehicle_category,
                       'samples', samples,
                       'on_time_ratio', on_time_ratio,
                       'mean_delay_seconds', mean_delay_seconds
                   ) ORDER BY position
               )
               FROM least_ranked
               WHERE position <= $2
           ),
           '[]'::jsonb
       ) AS least_punctual,
       to_jsonb(totals) AS totals
FROM totals
"""


class ReadPool(Protocol):
    async def fetch(
        self, query: str, *arguments: object
    ) -> Sequence[Mapping[str, object]]: ...

    async def fetchrow(
        self, query: str, *arguments: object
    ) -> Mapping[str, object] | None: ...


async def fetch_route_rows(pool: ReadPool) -> Sequence[Mapping[str, object]]:
    return await pool.fetch(ROUTE_LIST_SQL)


async def fetch_route_path_row(
    pool: ReadPool,
    route_id: str,
) -> Mapping[str, object] | None:
    return await pool.fetchrow(ROUTE_PATH_SQL, route_id)


async def fetch_stop_rows(
    pool: ReadPool,
    bbox: tuple[float, float, float, float],
    modes: Sequence[str] | None,
    limit: int,
) -> Sequence[Mapping[str, object]]:
    return await pool.fetch(STOPS_QUERY_SQL, *bbox, modes, limit)


async def fetch_daily_punctuality_row(
    pool: ReadPool,
    service_day: date,
    limit: int,
    min_samples: int,
) -> Mapping[str, object] | None:
    return await pool.fetchrow(
        PUNCTUALITY_DAILY_SQL,
        service_day,
        limit,
        min_samples,
    )
