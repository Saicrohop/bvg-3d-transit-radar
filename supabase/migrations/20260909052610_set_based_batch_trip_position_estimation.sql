-- Replace the first lateral-wrapper batch implementation with a fully set-based
-- query. This keeps one row namespace per input_index and avoids invoking the
-- single-trip function once per TripUpdate inside PostgreSQL.

CREATE OR REPLACE FUNCTION gtfs.estimate_trip_positions_batch(
    p_observed_at TIMESTAMPTZ,
    p_updates JSONB DEFAULT '[]'::JSONB
)
RETURNS TABLE (
    input_index INTEGER,
    trip_id TEXT,
    route_id TEXT,
    shape_id TEXT,
    previous_stop_id TEXT,
    next_stop_id TEXT,
    delay_seconds INTEGER,
    timing_source TEXT,
    estimated_next_arrival TIMESTAMPTZ,
    longitude DOUBLE PRECISION,
    latitude DOUBLE PRECISION,
    bearing_degrees DOUBLE PRECISION,
    speed_mps DOUBLE PRECISION,
    is_estimated BOOLEAN,
    position_status TEXT,
    route_type INTEGER,
    route_short_name TEXT
)
LANGUAGE sql
STABLE
SET search_path = pg_catalog, gtfs, extensions
AS $$
WITH batch_input AS (
    SELECT
        (input.ordinality - 1)::INTEGER AS input_index,
        NULLIF(input.value ->> 'trip_id', '') AS trip_id,
        NULLIF(input.value ->> 'service_date', '')::DATE AS service_date,
        COALESCE(
            input.value -> 'stop_time_updates',
            '[]'::JSONB
        ) AS stop_time_updates
    FROM jsonb_array_elements(
        COALESCE(p_updates, '[]'::JSONB)
    ) WITH ORDINALITY AS input(value, ordinality)
),
dynamic_updates AS (
    SELECT
        batch_input.input_index,
        NULLIF(update_item ->> 'stop_sequence', '')::INTEGER AS stop_sequence,
        NULLIF(update_item ->> 'stop_id', '') AS stop_id,
        NULLIF(update_item ->> 'arrival_time', '')::BIGINT AS arrival_time,
        NULLIF(update_item ->> 'arrival_delay_seconds', '')::INTEGER
            AS arrival_delay_seconds,
        NULLIF(update_item ->> 'departure_time', '')::BIGINT AS departure_time,
        NULLIF(update_item ->> 'departure_delay_seconds', '')::INTEGER
            AS departure_delay_seconds
    FROM batch_input
    CROSS JOIN LATERAL jsonb_array_elements(
        batch_input.stop_time_updates
    ) AS update_item
),
scheduled_stop_times AS (
    SELECT
        batch_input.input_index,
        stop_time.trip_id,
        stop_time.stop_id,
        stop_time.stop_sequence,
        stop_time.shape_fraction,
        (
            batch_input.service_date::TIMESTAMP
            + gtfs.gtfs_time_to_interval(stop_time.arrival_time)
        ) AT TIME ZONE 'Europe/Berlin' AS scheduled_arrival,
        (
            batch_input.service_date::TIMESTAMP
            + gtfs.gtfs_time_to_interval(stop_time.departure_time)
        ) AT TIME ZONE 'Europe/Berlin' AS scheduled_departure
    FROM batch_input
    JOIN gtfs.stop_times AS stop_time
      ON stop_time.trip_id = batch_input.trip_id
),
estimated_stop_times AS (
    SELECT
        scheduled.*,
        COALESCE(
            to_timestamp(dynamic.arrival_time::DOUBLE PRECISION),
            scheduled.scheduled_arrival
                + COALESCE(dynamic.arrival_delay_seconds, 0) * INTERVAL '1 second'
        ) AS estimated_arrival,
        CASE
            WHEN dynamic.arrival_time IS NOT NULL THEN 'absolute_realtime_time'
            WHEN dynamic.arrival_delay_seconds IS NOT NULL THEN 'realtime_delay'
            ELSE 'schedule_only'
        END AS arrival_timing_source,
        COALESCE(
            to_timestamp(dynamic.departure_time::DOUBLE PRECISION),
            scheduled.scheduled_departure
                + COALESCE(dynamic.departure_delay_seconds, 0) * INTERVAL '1 second'
        ) AS estimated_departure
    FROM scheduled_stop_times AS scheduled
    LEFT JOIN LATERAL (
        SELECT update_value.*
        FROM dynamic_updates AS update_value
        WHERE update_value.input_index = scheduled.input_index
          AND (
              (
                  update_value.stop_sequence IS NOT NULL
                  AND update_value.stop_sequence = scheduled.stop_sequence
              ) OR (
                  update_value.stop_sequence IS NULL
                  AND update_value.stop_id = scheduled.stop_id
              )
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
        LEAD(estimated.scheduled_arrival) OVER stop_order
            AS next_scheduled_arrival,
        LEAD(estimated.estimated_arrival) OVER stop_order
            AS next_estimated_arrival,
        LEAD(estimated.arrival_timing_source) OVER stop_order
            AS next_arrival_timing_source
    FROM estimated_stop_times AS estimated
    WINDOW stop_order AS (
        PARTITION BY estimated.input_index
        ORDER BY estimated.stop_sequence
    )
),
active_candidates AS (
    SELECT
        sequenced.*,
        EXTRACT(
            EPOCH FROM p_observed_at - sequenced.estimated_departure
        ) / NULLIF(
            EXTRACT(
                EPOCH FROM sequenced.next_estimated_arrival
                    - sequenced.estimated_departure
            ),
            0
        ) AS segment_progress
    FROM sequenced_stop_times AS sequenced
    WHERE sequenced.estimated_departure <= p_observed_at
      AND sequenced.next_estimated_arrival >= p_observed_at
      AND sequenced.shape_fraction IS NOT NULL
      AND sequenced.next_shape_fraction IS NOT NULL
      AND sequenced.next_shape_fraction > sequenced.shape_fraction
      AND sequenced.next_estimated_arrival > sequenced.estimated_departure
),
ranked_active_segments AS (
    SELECT
        active.*,
        ROW_NUMBER() OVER (
            PARTITION BY active.input_index
            ORDER BY active.stop_sequence DESC
        ) AS segment_rank
    FROM active_candidates AS active
),
active_segment AS (
    SELECT ranked.*
    FROM ranked_active_segments AS ranked
    WHERE ranked.segment_rank = 1
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
                * GREATEST(0.0, LEAST(1.0, segment.segment_progress))
                AS interpolated_fraction
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
    point.input_index,
    point.trip_id,
    point.route_id,
    point.shape_id,
    point.stop_id AS previous_stop_id,
    point.next_stop_id,
    CASE
        WHEN point.next_arrival_timing_source = 'schedule_only' THEN NULL
        ELSE ROUND(
            EXTRACT(
                EPOCH FROM point.next_estimated_arrival
                    - point.next_scheduled_arrival
            )
        )::INTEGER
    END AS delay_seconds,
    point.next_arrival_timing_source AS timing_source,
    point.next_estimated_arrival AS estimated_next_arrival,
    extensions.st_x(point.point_4326) AS longitude,
    extensions.st_y(point.point_4326) AS latitude,
    MOD(
        (
            DEGREES(
                extensions.st_azimuth(
                    point.bearing_start_25833,
                    point.bearing_end_25833
                )
            ) + 360.0
        )::NUMERIC,
        360.0::NUMERIC
    )::DOUBLE PRECISION AS bearing_degrees,
    extensions.st_distance(
        extensions.st_lineinterpolatepoint(
            point.geom_25833,
            point.shape_fraction
        ),
        extensions.st_lineinterpolatepoint(
            point.geom_25833,
            point.next_shape_fraction
        )
    ) / NULLIF(
        EXTRACT(
            EPOCH FROM point.next_estimated_arrival - point.estimated_departure
        ),
        0
    ) AS speed_mps,
    TRUE AS is_estimated,
    'estimated_from_trip_update'::TEXT AS position_status,
    route.route_type,
    route.route_short_name
FROM interpolated_points AS point
LEFT JOIN gtfs.routes AS route ON route.route_id = point.route_id
ORDER BY point.input_index;
$$;

COMMENT ON FUNCTION gtfs.estimate_trip_positions_batch(TIMESTAMPTZ, JSONB) IS
    'Set-based bounded TripUpdate interpolation with stable input indexes and route metadata.';

REVOKE ALL ON FUNCTION gtfs.estimate_trip_positions_batch(TIMESTAMPTZ, JSONB)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION gtfs.estimate_trip_positions_batch(TIMESTAMPTZ, JSONB)
    TO service_role;
