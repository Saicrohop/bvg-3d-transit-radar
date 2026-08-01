-- Phase 2 — import the VBB static GTFS files required for TripUpdate
-- interpolation inside the local Supabase PostgreSQL container.
--
-- Source files are staged by scripts/import_static_gtfs_local.sh at
-- /tmp/bvg-gtfs-import. This script is local-only and intentionally uses psql
-- \copy so the database role never needs server-file privileges.

BEGIN;

-- A static feed replacement must be atomic from the application's point of
-- view. Include children before their referenced parent tables.
TRUNCATE TABLE gtfs.stop_times, gtfs.trips, gtfs.shapes, gtfs.stops, gtfs.routes;

-- Explicit column lists match the inspected current VBB export rather than the
-- physical table order. Do not add positional COPY imports here.
\copy gtfs.routes (route_id, agency_id, route_short_name, route_long_name, route_type, route_color, route_text_color, route_desc) FROM '/tmp/bvg-gtfs-import/routes.txt' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy gtfs.stops (stop_id, stop_code, stop_name, stop_desc, stop_lat, stop_lon, location_type, parent_station, wheelchair_boarding, platform_code, zone_id, level_id) FROM '/tmp/bvg-gtfs-import/stops.txt' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy gtfs.shapes (shape_id, shape_pt_lat, shape_pt_lon, shape_pt_sequence) FROM '/tmp/bvg-gtfs-import/shapes.txt' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy gtfs.trips (route_id, service_id, trip_id, trip_headsign, trip_short_name, direction_id, block_id, shape_id, wheelchair_accessible, bikes_allowed) FROM '/tmp/bvg-gtfs-import/trips.txt' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy gtfs.stop_times (trip_id, stop_id, stop_sequence, pickup_type, drop_off_type, stop_headsign, arrival_time, departure_time) FROM '/tmp/bvg-gtfs-import/stop_times.txt' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')

COMMIT;
