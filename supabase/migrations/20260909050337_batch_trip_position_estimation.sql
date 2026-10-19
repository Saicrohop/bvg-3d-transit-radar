-- Phase 2 performance correction — batch TripUpdate interpolation into bounded
-- database round trips while preserving the existing single-update function.

CREATE FUNCTION gtfs.estimate_trip_positions_batch(
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
)
SELECT
    batch_input.input_index,
    estimate.trip_id,
    estimate.route_id,
    estimate.shape_id,
    estimate.previous_stop_id,
    estimate.next_stop_id,
    estimate.delay_seconds,
    estimate.timing_source,
    estimate.estimated_next_arrival,
    estimate.longitude,
    estimate.latitude,
    estimate.bearing_degrees,
    estimate.speed_mps,
    estimate.is_estimated,
    estimate.position_status,
    route.route_type,
    route.route_short_name
FROM batch_input
CROSS JOIN LATERAL gtfs.estimate_trip_position(
    batch_input.trip_id,
    batch_input.service_date,
    p_observed_at,
    batch_input.stop_time_updates
) AS estimate
LEFT JOIN gtfs.routes AS route ON route.route_id = estimate.route_id
ORDER BY batch_input.input_index;
$$;

COMMENT ON FUNCTION gtfs.estimate_trip_positions_batch(TIMESTAMPTZ, JSONB) IS
    'Estimates a bounded batch of TripUpdates in input order and returns route metadata in the same database round trip.';

REVOKE ALL ON FUNCTION gtfs.estimate_trip_positions_batch(TIMESTAMPTZ, JSONB)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION gtfs.estimate_trip_positions_batch(TIMESTAMPTZ, JSONB)
    TO service_role;
