-- Phase 1 — run this AFTER routes.txt, trips.txt, stops.txt and shapes.txt
-- have been loaded into the corresponding gtfs.* tables.
--
-- Do not wrap this entire script in BEGIN/COMMIT. Future refreshes may use
-- REFRESH MATERIALIZED VIEW CONCURRENTLY, which PostgreSQL forbids inside a
-- transaction block.

-- The first refresh cannot be CONCURRENTLY because the materialized view was
-- created WITH NO DATA. It is safe during the one-time initial static import.
REFRESH MATERIALIZED VIEW gtfs.route_shapes_geom;

-- Build non-primary indexes after the bulk load, which is substantially faster
-- than maintaining them for every imported GTFS row.
CREATE INDEX IF NOT EXISTS trips_route_id_idx
    ON gtfs.trips (route_id);

CREATE INDEX IF NOT EXISTS trips_shape_id_idx
    ON gtfs.trips (shape_id)
    WHERE shape_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS stops_geom_gix
    ON gtfs.stops USING GIST (geom);

-- This unique index is a prerequisite for future non-blocking refreshes:
-- REFRESH MATERIALIZED VIEW CONCURRENTLY gtfs.route_shapes_geom;
CREATE UNIQUE INDEX IF NOT EXISTS route_shapes_geom_shape_id_key
    ON gtfs.route_shapes_geom (shape_id);

CREATE INDEX IF NOT EXISTS route_shapes_geom_4326_gix
    ON gtfs.route_shapes_geom USING GIST (geom_4326);

CREATE INDEX IF NOT EXISTS route_shapes_geom_25833_gix
    ON gtfs.route_shapes_geom USING GIST (geom_25833);

ANALYZE gtfs.routes;
ANALYZE gtfs.trips;
ANALYZE gtfs.stops;
ANALYZE gtfs.shapes;
ANALYZE gtfs.route_shapes_geom;

-- Phase-1 validation: all values should be sensible before proceeding.
SELECT
    (SELECT COUNT(*) FROM gtfs.routes) AS routes,
    (SELECT COUNT(*) FROM gtfs.trips) AS trips,
    (SELECT COUNT(*) FROM gtfs.stops) AS stops,
    (SELECT COUNT(*) FROM gtfs.shapes) AS shape_points,
    (SELECT COUNT(*) FROM gtfs.route_shapes_geom) AS route_shape_lines,
    (SELECT COUNT(*) FROM gtfs.stops WHERE geom IS NULL) AS stops_without_geom,
    (SELECT COUNT(*) FROM gtfs.route_shapes_geom
      WHERE NOT extensions.st_isvalid(geom_4326)) AS invalid_wgs84_shape_lines;

-- For every later static GTFS replacement, refresh after the replacement has
-- completed. This statement is intentionally a comment: execute it directly,
-- outside an explicit transaction block.
-- REFRESH MATERIALIZED VIEW CONCURRENTLY gtfs.route_shapes_geom;
