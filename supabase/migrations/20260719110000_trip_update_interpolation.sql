-- Phase 2 — TripUpdate-backed estimated vehicle positions.
--
-- GTFS-Realtime is decoded exclusively by the backend. This migration stores
-- static stop schedules and exposes a server-only PostGIS interpolation function
-- that can turn a matching TripUpdate into an estimated position on its shape.

CREATE TABLE IF NOT EXISTS gtfs.stop_times (
    trip_id            TEXT NOT NULL,
    stop_id            TEXT NOT NULL,
    stop_sequence      INTEGER NOT NULL,
    pickup_type        SMALLINT,
    drop_off_type      SMALLINT,
    stop_headsign      TEXT,
    arrival_time       TEXT NOT NULL,
    departure_time     TEXT NOT NULL,
    shape_fraction     DOUBLE PRECISION,

    CONSTRAINT stop_times_pkey PRIMARY KEY (trip_id, stop_sequence),
    CONSTRAINT stop_times_trip_fkey FOREIGN KEY (trip_id) REFERENCES gtfs.trips (trip_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT stop_times_stop_fkey FOREIGN KEY (stop_id) REFERENCES gtfs.stops (stop_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT stop_times_sequence_nonnegative CHECK (stop_sequence >= 0),
    CONSTRAINT stop_times_arrival_format CHECK (
        arrival_time ~ '^[0-9]{1,3}:[0-5][0-9]:[0-5][0-9]$'
    ),
    CONSTRAINT stop_times_departure_format CHECK (
        departure_time ~ '^[0-9]{1,3}:[0-5][0-9]:[0-5][0-9]$'
    ),
    CONSTRAINT stop_times_shape_fraction_range CHECK (
        shape_fraction IS NULL OR (shape_fraction >= 0.0 AND shape_fraction <= 1.0)
    )
);

COMMENT ON TABLE gtfs.stop_times IS
    'Static stop schedule for each trip, including a PostGIS-derived fraction on the trip shape.';
COMMENT ON COLUMN gtfs.stop_times.shape_fraction IS
    'Closest normalized location of the stop on its trip shape; populated after static import.';

-- GTFS permits times beyond 24:00:00. PostgreSQL TIME does not preserve that
-- service-day meaning, so retain source text and convert it to an interval only
-- when resolving a TripUpdate for a known service date.
CREATE OR REPLACE FUNCTION gtfs.gtfs_time_to_interval(p_gtfs_time TEXT)
RETURNS INTERVAL
LANGUAGE sql
IMMUTABLE
STRICT
PARALLEL SAFE
SET search_path = pg_catalog
AS $$
    SELECT make_interval(
        hours => split_part(p_gtfs_time, ':', 1)::INTEGER,
        mins => split_part(p_gtfs_time, ':', 2)::INTEGER,
        secs => split_part(p_gtfs_time, ':', 3)::DOUBLE PRECISION
    );
$$;

COMMENT ON FUNCTION gtfs.gtfs_time_to_interval(TEXT) IS
    'Converts a validated GTFS HH:MM:SS value, including hours beyond 24, into a service-day interval.';

-- p_stop_time_updates is backend-generated JSON only. Each element may contain:
-- stop_sequence, stop_id, arrival_time, arrival_delay_seconds,
-- departure_time and departure_delay_seconds. Absolute GTFS-RT event time wins
-- over delay; delay falls back to the static scheduled time.
CREATE OR REPLACE FUNCTION gtfs.estimate_trip_position(
    p_trip_id TEXT,
    p_service_date DATE,
    p_observed_at TIMESTAMPTZ,
    p_stop_time_updates JSONB DEFAULT '[]'::JSONB
)
RETURNS TABLE (
    trip_id TEXT,
    route_id TEXT,
    shape_id TEXT,
    previous_stop_id TEXT,
    next_stop_id TEXT,
    delay_seconds INTEGER,
    estimated_next_arrival TIMESTAMPTZ,
    longitude DOUBLE PRECISION,
    latitude DOUBLE PRECISION,
    bearing_degrees DOUBLE PRECISION,
    speed_mps DOUBLE PRECISION,
    is_estimated BOOLEAN,
    position_status TEXT
)
LANGUAGE sql
STABLE
SET search_path = pg_catalog, gtfs, extensions
AS $$
WITH dynamic_updates AS (
    SELECT
        NULLIF(update_item ->> 'stop_sequence', '')::INTEGER AS stop_sequence,
        NULLIF(update_item ->> 'stop_id', '') AS stop_id,
        NULLIF(update_item ->> 'arrival_time', '')::BIGINT AS arrival_time,
        NULLIF(update_item ->> 'arrival_delay_seconds', '')::INTEGER AS arrival_delay_seconds,
        NULLIF(update_item ->> 'departure_time', '')::BIGINT AS departure_time,
        NULLIF(update_item ->> 'departure_delay_seconds', '')::INTEGER AS departure_delay_seconds
    FROM jsonb_array_elements(COALESCE(p_stop_time_updates, '[]'::JSONB)) AS update_item
),
scheduled_stop_times AS (
    SELECT
        stop_time.trip_id,
        stop_time.stop_id,
        stop_time.stop_sequence,
        stop_time.shape_fraction,
        (
            p_service_date::TIMESTAMP
            + gtfs.gtfs_time_to_interval(stop_time.arrival_time)
        ) AT TIME ZONE 'Europe/Berlin' AS scheduled_arrival,
        (
            p_service_date::TIMESTAMP
            + gtfs.gtfs_time_to_interval(stop_time.departure_time)
        ) AT TIME ZONE 'Europe/Berlin' AS scheduled_departure
    FROM gtfs.stop_times AS stop_time
    WHERE stop_time.trip_id = p_trip_id
),
estimated_stop_times AS (
    SELECT
        scheduled.*,
        COALESCE(
            to_timestamp(dynamic.arrival_time::DOUBLE PRECISION),
            scheduled.scheduled_arrival
                + COALESCE(dynamic.arrival_delay_seconds, 0) * INTERVAL '1 second'
        ) AS estimated_arrival,
        COALESCE(
            to_timestamp(dynamic.departure_time::DOUBLE PRECISION),
            scheduled.scheduled_departure
                + COALESCE(dynamic.departure_delay_seconds, 0) * INTERVAL '1 second'
        ) AS estimated_departure
    FROM scheduled_stop_times AS scheduled
    LEFT JOIN LATERAL (
        SELECT update_value.*
        FROM dynamic_updates AS update_value
        WHERE (
            update_value.stop_sequence IS NOT NULL
            AND update_value.stop_sequence = scheduled.stop_sequence
        ) OR (
            update_value.stop_sequence IS NULL
            AND update_value.stop_id = scheduled.stop_id
        )
        ORDER BY CASE
            WHEN update_value.stop_sequence = scheduled.stop_sequence THEN 0
            ELSE 1
        END
        LIMIT 1
    ) AS dynamic ON TRUE
),
sequenced_stop_times AS (
    SELECT
        estimated.*,
        LEAD(estimated.stop_id) OVER stop_order AS next_stop_id,
        LEAD(estimated.shape_fraction) OVER stop_order AS next_shape_fraction,
        LEAD(estimated.scheduled_arrival) OVER stop_order AS next_scheduled_arrival,
        LEAD(estimated.estimated_arrival) OVER stop_order AS next_estimated_arrival
    FROM estimated_stop_times AS estimated
    WINDOW stop_order AS (ORDER BY estimated.stop_sequence)
),
active_segment AS (
    SELECT
        sequenced.*,
        EXTRACT(
            EPOCH FROM p_observed_at - sequenced.estimated_departure
        ) / NULLIF(
            EXTRACT(
                EPOCH FROM sequenced.next_estimated_arrival - sequenced.estimated_departure
            ),
            0
        ) AS segment_progress
    FROM sequenced_stop_times AS sequenced
    WHERE sequenced.estimated_departure <= p_observed_at
      AND sequenced.next_estimated_arrival >= p_observed_at
      AND sequenced.shape_fraction IS NOT NULL
      AND sequenced.next_shape_fraction IS NOT NULL
      -- Nearest-point projection is ambiguous on looped shapes. Return no
      -- estimate rather than place a vehicle on the wrong leg of the route.
      AND sequenced.next_shape_fraction > sequenced.shape_fraction
      AND sequenced.next_estimated_arrival > sequenced.estimated_departure
    ORDER BY sequenced.stop_sequence DESC
    LIMIT 1
),
interpolated_segment AS (
    SELECT
        segment.*,
        trip.route_id,
        trip.shape_id,
        shape.geom_4326,
        shape.geom_25833,
        segment.shape_fraction
            + (segment.next_shape_fraction - segment.shape_fraction)
                * GREATEST(0.0, LEAST(1.0, segment.segment_progress)) AS interpolated_fraction
    FROM active_segment AS segment
    JOIN gtfs.trips AS trip ON trip.trip_id = segment.trip_id
    JOIN gtfs.route_shapes_geom AS shape ON shape.shape_id = trip.shape_id
),
interpolated_points AS (
    SELECT
        segment.*,
        extensions.st_lineinterpolatepoint(
            segment.geom_4326,
            segment.interpolated_fraction
        ) AS point_4326,
        extensions.st_lineinterpolatepoint(
            segment.geom_25833,
            segment.interpolated_fraction
        ) AS point_25833,
        extensions.st_lineinterpolatepoint(
            segment.geom_25833,
            GREATEST(0.0, segment.interpolated_fraction - 0.0001)
        ) AS bearing_start_25833,
        extensions.st_lineinterpolatepoint(
            segment.geom_25833,
            LEAST(1.0, segment.interpolated_fraction + 0.0001)
        ) AS bearing_end_25833
    FROM interpolated_segment AS segment
)
SELECT
    point.trip_id,
    point.route_id,
    point.shape_id,
    point.stop_id AS previous_stop_id,
    point.next_stop_id,
    ROUND(
        EXTRACT(EPOCH FROM point.next_estimated_arrival - point.next_scheduled_arrival)
    )::INTEGER AS delay_seconds,
    point.next_estimated_arrival AS estimated_next_arrival,
    extensions.st_x(point.point_4326) AS longitude,
    extensions.st_y(point.point_4326) AS latitude,
    MOD(
        (
            DEGREES(extensions.st_azimuth(point.bearing_start_25833, point.bearing_end_25833))
                + 360.0
        )::NUMERIC,
        360.0::NUMERIC
    )::DOUBLE PRECISION AS bearing_degrees,
    extensions.st_distance(
        extensions.st_lineinterpolatepoint(point.geom_25833, point.shape_fraction),
        extensions.st_lineinterpolatepoint(point.geom_25833, point.next_shape_fraction)
    ) / NULLIF(
        EXTRACT(EPOCH FROM point.next_estimated_arrival - point.estimated_departure),
        0
    ) AS speed_mps,
    TRUE AS is_estimated,
    'estimated_from_trip_update'::TEXT AS position_status
FROM interpolated_points AS point;
$$;

COMMENT ON FUNCTION gtfs.estimate_trip_position(TEXT, DATE, TIMESTAMPTZ, JSONB) IS
    'Returns a conservative, TripUpdate-based estimated vehicle position on a static GTFS shape, or no row when a safe segment cannot be established.';

ALTER TABLE gtfs.stop_times ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE gtfs.stop_times FROM anon, authenticated;
REVOKE ALL ON FUNCTION gtfs.gtfs_time_to_interval(TEXT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION gtfs.estimate_trip_position(TEXT, DATE, TIMESTAMPTZ, JSONB)
    FROM PUBLIC, anon, authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE gtfs.stop_times TO service_role;
GRANT EXECUTE ON FUNCTION gtfs.gtfs_time_to_interval(TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION gtfs.estimate_trip_position(TEXT, DATE, TIMESTAMPTZ, JSONB)
    TO service_role;
