BEGIN;

-- Stop-mode lookups include platform children when rendering parent stations.
-- This partial index supports those joins without inflating rows for root stations.
CREATE INDEX IF NOT EXISTS gtfs_stops_parent_station_idx
    ON gtfs.stops (parent_station)
    WHERE parent_station IS NOT NULL;

COMMIT;
