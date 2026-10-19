BEGIN;

CREATE MATERIALIZED VIEW gtfs.stop_vehicle_modes AS
WITH stop_modes AS (
    SELECT DISTINCT
           stop_time.stop_id,
           CASE
               WHEN route.route_type IN (1, 400) THEN 'u_bahn'
               WHEN route.route_type IN (2, 109)
                    AND route.route_short_name LIKE 'S%' THEN 's_bahn'
               WHEN route.route_type = 100 THEN 'regional'
               WHEN route.route_type IN (3, 700) THEN 'bus'
               WHEN route.route_type IN (0, 900) THEN 'tram'
               ELSE NULL
           END AS vehicle_category
    FROM gtfs.stop_times AS stop_time
    JOIN gtfs.trips AS trip USING (trip_id)
    JOIN gtfs.routes AS route USING (route_id)
), stop_and_station_modes AS (
    SELECT stop_id, vehicle_category
    FROM stop_modes
    WHERE vehicle_category IS NOT NULL

    UNION

    SELECT stop.parent_station AS stop_id, stop_modes.vehicle_category
    FROM stop_modes
    JOIN gtfs.stops AS stop USING (stop_id)
    WHERE stop.location_type = 0
      AND stop.parent_station IS NOT NULL
      AND stop_modes.vehicle_category IS NOT NULL
)
SELECT DISTINCT stop_id, vehicle_category
FROM stop_and_station_modes
WITH NO DATA;

CREATE UNIQUE INDEX gtfs_stop_vehicle_modes_stop_category_idx
    ON gtfs.stop_vehicle_modes (stop_id, vehicle_category);

REVOKE ALL ON TABLE gtfs.stop_vehicle_modes FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE gtfs.stop_vehicle_modes TO service_role;

COMMENT ON MATERIALIZED VIEW gtfs.stop_vehicle_modes IS
    'Known VBB vehicle categories serving each GTFS stop or parent station.';

-- Populate immediately for this already-imported local GTFS; the import pipeline
-- refreshes it after future static GTFS replacements.
REFRESH MATERIALIZED VIEW gtfs.stop_vehicle_modes;
ANALYZE gtfs.stop_vehicle_modes;

COMMIT;
