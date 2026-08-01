-- Phase 1 — import the inspected VBB static GTFS export inside the local
-- Supabase PostgreSQL container. Source files are staged at /tmp/bvg-gtfs-import.
--
-- The column lists deliberately match the headers in the current VBB export,
-- rather than relying on each table's physical column order.

BEGIN;

-- This makes local re-imports deterministic. Do not run against a remote
-- production database.
TRUNCATE TABLE gtfs.trips, gtfs.shapes, gtfs.stops, gtfs.routes;

-- \copy runs in psql, which reads the local container files and streams them
-- through COPY FROM STDIN. This deliberately avoids granting server-file
-- privileges to the Supabase database role.
\copy gtfs.routes (route_id, agency_id, route_short_name, route_long_name, route_type, route_color, route_text_color, route_desc) FROM '/tmp/bvg-gtfs-import/routes.txt' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy gtfs.stops (stop_id, stop_code, stop_name, stop_desc, stop_lat, stop_lon, location_type, parent_station, wheelchair_boarding, platform_code, zone_id, level_id) FROM '/tmp/bvg-gtfs-import/stops.txt' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy gtfs.shapes (shape_id, shape_pt_lat, shape_pt_lon, shape_pt_sequence) FROM '/tmp/bvg-gtfs-import/shapes.txt' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy gtfs.trips (route_id, service_id, trip_id, trip_headsign, trip_short_name, direction_id, block_id, shape_id, wheelchair_accessible, bikes_allowed) FROM '/tmp/bvg-gtfs-import/trips.txt' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')

COMMIT;
