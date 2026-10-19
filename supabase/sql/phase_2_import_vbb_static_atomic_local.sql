-- Local-only atomic replacement. Invoke ONLY through the importer with
-- -X --single-transaction -v ON_ERROR_STOP=1, from its isolated staging cwd.
-- No transaction boundaries here: the one outer transaction also covers the
-- existing non-concurrent refresh, indexes, projections and health gate.
-- ACCESS EXCLUSIVE locks last until commit/rollback: pause the worker for this
-- maintenance operation. TRUNCATE is not safe for pre-existing MVCC snapshots.

SET LOCAL lock_timeout = '5s';

DO $import_lock$
BEGIN
    IF NOT pg_try_advisory_xact_lock(hashtextextended('bvg-radar-static-import', 0)) THEN
        RAISE EXCEPTION 'Another static GTFS import is in progress';
    END IF;
END
$import_lock$;

TRUNCATE TABLE gtfs.stop_times, gtfs.trips, gtfs.shapes, gtfs.stops, gtfs.routes;

-- Explicit VBB column order mirrors the historical import, without its early
-- COMMIT. Paths are relative to docker exec's per-run staging working directory.
\copy gtfs.routes (route_id, agency_id, route_short_name, route_long_name, route_type, route_color, route_text_color, route_desc) FROM 'routes.txt' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy gtfs.stops (stop_id, stop_code, stop_name, stop_desc, stop_lat, stop_lon, location_type, parent_station, wheelchair_boarding, platform_code, zone_id, level_id) FROM 'stops.txt' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy gtfs.shapes (shape_id, shape_pt_lat, shape_pt_lon, shape_pt_sequence) FROM 'shapes.txt' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy gtfs.trips (route_id, service_id, trip_id, trip_headsign, trip_short_name, direction_id, block_id, shape_id, wheelchair_accessible, bikes_allowed) FROM 'trips.txt' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy gtfs.stop_times (trip_id, stop_id, stop_sequence, pickup_type, drop_off_type, stop_headsign, arrival_time, departure_time) FROM 'stop_times.txt' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')

\ir phase_1_after_static_gtfs_import.sql
\ir phase_2_after_stop_times_import.sql

-- Informational SELECTs in the reused scripts are not a gate: fail explicitly
-- before the outer commit. This uses read-only checks, not estimator functions
-- that may have write side effects. No privileges/RLS/functions are changed.
DO $health$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM gtfs.routes)
       OR NOT EXISTS (SELECT 1 FROM gtfs.trips)
       OR NOT EXISTS (SELECT 1 FROM gtfs.stops)
       OR NOT EXISTS (SELECT 1 FROM gtfs.shapes)
       OR NOT EXISTS (SELECT 1 FROM gtfs.stop_times)
       OR NOT EXISTS (SELECT 1 FROM gtfs.route_shapes_geom) THEN
        RAISE EXCEPTION 'Static GTFS health gate: empty base or derived table';
    END IF;

    IF (SELECT COUNT(*) FROM gtfs.route_shapes_geom) <> (
        SELECT COUNT(*) FROM (
            SELECT shape_id FROM gtfs.shapes GROUP BY shape_id HAVING COUNT(*) >= 2
        ) AS eligible_shapes
    ) THEN
        RAISE EXCEPTION 'Static GTFS health gate: incomplete shape refresh';
    END IF;

    IF EXISTS (
        SELECT 1 FROM gtfs.route_shapes_geom
        WHERE geom_4326 IS NULL OR geom_25833 IS NULL
           OR NOT extensions.st_isvalid(geom_4326)
           OR NOT extensions.st_isvalid(geom_25833)
           OR extensions.st_isempty(geom_4326)
           OR extensions.st_length(geom_25833) <= 0
    ) THEN
        RAISE EXCEPTION 'Static GTFS health gate: invalid shape geometry';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM gtfs.stop_times AS stop_time
        JOIN gtfs.trips AS trip ON trip.trip_id = stop_time.trip_id
        JOIN gtfs.route_shapes_geom AS shape ON shape.shape_id = trip.shape_id
        WHERE stop_time.shape_fraction IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'Static GTFS health gate: no projected stop times';
    END IF;

    IF EXISTS (
        SELECT 1 FROM gtfs.stop_times AS stop_time
        JOIN gtfs.trips AS trip ON trip.trip_id = stop_time.trip_id
        JOIN gtfs.stops AS stop ON stop.stop_id = stop_time.stop_id
        JOIN gtfs.route_shapes_geom AS shape ON shape.shape_id = trip.shape_id
        WHERE stop_time.shape_fraction IS NULL
           OR NOT (stop_time.shape_fraction BETWEEN 0.0 AND 1.0)
    ) THEN
        RAISE EXCEPTION 'Static GTFS health gate: incomplete or invalid projection';
    END IF;

    -- Shape-less/one-point trips and loop/non-monotonic segments are deliberately
    -- not rejected globally; the existing runtime suppresses unsafe estimates.
END
$health$;
