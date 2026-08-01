-- Phase 2 — run after phase_1_after_static_gtfs_import.sql and after
-- gtfs.stop_times has been loaded from the local VBB export.
--
-- route_shapes_geom must already be populated because the update below projects
-- every scheduled stop onto its static LineString.

-- Populate once per static import, not on every realtime poll. This keeps the
-- live interpolation query to arithmetic plus ST_LineInterpolatePoint.
UPDATE gtfs.stop_times AS stop_time
SET shape_fraction = gtfs.clamp_shape_fraction(
    extensions.st_linelocatepoint(shape.geom_4326, stop.geom)
)
FROM gtfs.trips AS trip,
     gtfs.stops AS stop,
     gtfs.route_shapes_geom AS shape
WHERE trip.trip_id = stop_time.trip_id
  AND stop.stop_id = stop_time.stop_id
  AND shape.shape_id = trip.shape_id;

-- The primary key already supports ordered lookup of a trip's stop schedule.
-- This index supports the foreign key and stop-centric diagnostics.
CREATE INDEX IF NOT EXISTS stop_times_stop_id_idx
    ON gtfs.stop_times (stop_id);

ANALYZE gtfs.stop_times;

-- Validation: a NULL projection or decreasing consecutive fractions cannot
-- safely be interpolated without a loop-aware map-matching strategy. The
-- runtime function intentionally returns no estimate for those segments.
WITH ordered_stop_times AS (
    SELECT
        trip_id,
        stop_sequence,
        shape_fraction,
        LEAD(shape_fraction) OVER (
            PARTITION BY trip_id
            ORDER BY stop_sequence
        ) AS next_shape_fraction
    FROM gtfs.stop_times
)
SELECT
    (SELECT COUNT(*) FROM gtfs.stop_times) AS stop_times,
    (SELECT COUNT(*) FROM gtfs.stop_times WHERE shape_fraction IS NULL)
        AS stop_times_without_shape_fraction,
    COUNT(*) FILTER (
        WHERE next_shape_fraction IS NOT NULL
          AND next_shape_fraction <= shape_fraction
    ) AS non_monotonic_shape_segments
FROM ordered_stop_times;
