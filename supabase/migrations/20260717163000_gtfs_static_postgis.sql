-- Phase 1 — VBB/BVG GTFS static data foundation for Supabase + PostGIS
--
-- Scope: static GTFS tables and spatial derivatives only.
-- The browser must never download or parse GTFS-Realtime protobuf feeds.
--
-- This migration is written for Supabase PostgreSQL, where extensions live in
-- the `extensions` schema. Execute it with the Supabase SQL Editor or `supabase db push`.

CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA extensions;

-- Keep GTFS source data out of Supabase's default PostgREST-exposed `public`
-- schema. The FastAPI backend will be the only application-facing gateway.
CREATE SCHEMA IF NOT EXISTS gtfs;

COMMENT ON SCHEMA gtfs IS
  'Static VBB GTFS source data and backend-only PostGIS spatial assets.';

-- -----------------------------------------------------------------------------
-- GTFS source tables
-- Column order follows the standard GTFS text files so direct COPY/\copy is
-- possible. Optional fields are retained only to make static imports reliable.
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS gtfs.routes (
    route_id              TEXT PRIMARY KEY,
    agency_id             TEXT,
    route_short_name      TEXT,
    route_long_name       TEXT,
    route_desc            TEXT,
    route_type            INTEGER NOT NULL,
    route_url             TEXT,
    route_color           TEXT,
    route_text_color      TEXT,
    route_sort_order      INTEGER,
    continuous_pickup     SMALLINT,
    continuous_drop_off   SMALLINT,
    network               TEXT
);

CREATE TABLE IF NOT EXISTS gtfs.trips (
    route_id                TEXT NOT NULL REFERENCES gtfs.routes(route_id)
                                      ON UPDATE CASCADE ON DELETE RESTRICT,
    service_id              TEXT NOT NULL,
    trip_id                 TEXT PRIMARY KEY,
    trip_headsign           TEXT,
    trip_short_name         TEXT,
    direction_id            SMALLINT CHECK (direction_id IN (0, 1)),
    block_id                TEXT,
    shape_id                TEXT,
    wheelchair_accessible   SMALLINT,
    bikes_allowed           SMALLINT
);

CREATE TABLE IF NOT EXISTS gtfs.stops (
    stop_id                 TEXT PRIMARY KEY,
    stop_code               TEXT,
    stop_name               TEXT NOT NULL,
    tts_stop_name           TEXT,
    stop_desc               TEXT,
    stop_lat                DOUBLE PRECISION NOT NULL,
    stop_lon                DOUBLE PRECISION NOT NULL,
    zone_id                 TEXT,
    stop_url                TEXT,
    location_type           SMALLINT,
    parent_station          TEXT,
    stop_timezone           TEXT,
    wheelchair_boarding     SMALLINT,
    level_id                TEXT,
    platform_code           TEXT,

    -- Stored automatically on every insert/update; no manual UPDATE is needed
    -- after the GTFS import. Longitude must be X, latitude must be Y.
    geom extensions.geometry(Point, 4326)
        GENERATED ALWAYS AS (
            extensions.st_setsrid(
                extensions.st_makepoint(stop_lon, stop_lat),
                4326
            )
        ) STORED,

    CONSTRAINT stops_latitude_range CHECK (stop_lat BETWEEN -90.0 AND 90.0),
    CONSTRAINT stops_longitude_range CHECK (stop_lon BETWEEN -180.0 AND 180.0)
);

CREATE TABLE IF NOT EXISTS gtfs.shapes (
    shape_id                TEXT NOT NULL,
    shape_pt_lat            DOUBLE PRECISION NOT NULL,
    shape_pt_lon            DOUBLE PRECISION NOT NULL,
    shape_pt_sequence       INTEGER NOT NULL,
    shape_dist_traveled     DOUBLE PRECISION,

    CONSTRAINT shapes_pkey PRIMARY KEY (shape_id, shape_pt_sequence),
    CONSTRAINT shapes_latitude_range CHECK (shape_pt_lat BETWEEN -90.0 AND 90.0),
    CONSTRAINT shapes_longitude_range CHECK (shape_pt_lon BETWEEN -180.0 AND 180.0),
    CONSTRAINT shapes_sequence_nonnegative CHECK (shape_pt_sequence >= 0),
    CONSTRAINT shapes_distance_nonnegative CHECK (
        shape_dist_traveled IS NULL OR shape_dist_traveled >= 0
    )
);

COMMENT ON COLUMN gtfs.stops.geom IS
  'Generated WGS84 point geometry (longitude, latitude; SRID 4326).';
COMMENT ON COLUMN gtfs.shapes.shape_pt_sequence IS
  'GTFS ordering key used to rebuild each vehicle path as a LineString.';

-- -----------------------------------------------------------------------------
-- Derived spatial asset
--
-- geom_4326 is appropriate for MapLibre/Deck.gl serialization.
-- geom_25833 is Berlin's ETRS89 / UTM zone 33N metric projection and is kept
-- for accurate future server-side distance/snap calculations.
--
-- The materialized view starts empty because shapes.txt is imported afterwards.
-- Run supabase/sql/phase_1_after_static_gtfs_import.sql once the four files are
-- loaded. Shapes with fewer than two vertices are deliberately excluded.
-- -----------------------------------------------------------------------------

CREATE MATERIALIZED VIEW IF NOT EXISTS gtfs.route_shapes_geom AS
WITH shape_lines AS (
    SELECT
        shape_id,
        extensions.st_setsrid(
            extensions.st_makeline(
                extensions.st_makepoint(shape_pt_lon, shape_pt_lat)
                ORDER BY shape_pt_sequence
            ),
            4326
        )::extensions.geometry(LineString, 4326) AS geom_4326,
        COUNT(*)::INTEGER AS vertex_count
    FROM gtfs.shapes
    GROUP BY shape_id
    HAVING COUNT(*) >= 2
)
SELECT
    shape_id,
    geom_4326,
    extensions.st_transform(geom_4326, 25833)::extensions.geometry(LineString, 25833)
        AS geom_25833,
    vertex_count
FROM shape_lines
WITH NO DATA;

COMMENT ON MATERIALIZED VIEW gtfs.route_shapes_geom IS
  'One ordered WGS84 and metric LineString per GTFS shape, generated from gtfs.shapes.';

-- -----------------------------------------------------------------------------
-- Supabase access boundary
--
-- The static source data and materialized shapes remain backend-only. RLS
-- protects physical tables; materialized views do not implement RLS, so their
-- privileges are explicitly revoked. The Supabase service role bypasses RLS.
-- -----------------------------------------------------------------------------

ALTER TABLE gtfs.routes ENABLE ROW LEVEL SECURITY;
ALTER TABLE gtfs.trips ENABLE ROW LEVEL SECURITY;
ALTER TABLE gtfs.stops ENABLE ROW LEVEL SECURITY;
ALTER TABLE gtfs.shapes ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON SCHEMA gtfs FROM PUBLIC;
REVOKE ALL ON TABLE gtfs.routes, gtfs.trips, gtfs.stops, gtfs.shapes,
    gtfs.route_shapes_geom FROM anon, authenticated;

GRANT USAGE ON SCHEMA gtfs TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE gtfs.routes, gtfs.trips,
    gtfs.stops, gtfs.shapes TO service_role;
GRANT SELECT ON TABLE gtfs.route_shapes_geom TO service_role;
