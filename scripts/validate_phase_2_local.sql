-- Local integration validation for Phase 2. It uses real imported VBB static
-- data but does not persist any changes.

DO $$
DECLARE
    total_stop_times BIGINT;
    missing_fractions BIGINT;
    out_of_range_fractions BIGINT;
BEGIN
    SELECT
        COUNT(*),
        COUNT(*) FILTER (WHERE shape_fraction IS NULL),
        COUNT(*) FILTER (WHERE shape_fraction < 0.0 OR shape_fraction > 1.0)
    INTO total_stop_times, missing_fractions, out_of_range_fractions
    FROM gtfs.stop_times;

    IF total_stop_times = 0 OR missing_fractions <> 0 OR out_of_range_fractions <> 0 THEN
        RAISE EXCEPTION
            'Invalid stop-time projection state: total=%, missing=%, out_of_range=%',
            total_stop_times,
            missing_fractions,
            out_of_range_fractions;
    END IF;
END;
$$;

-- The clamp must absorb the one-ULP overflow/underflow values that PostGIS can
-- produce at line endpoints. Keep this deterministic instead of depending on
-- a trip_id that disappears whenever VBB publishes a new static schedule.
DO $$
DECLARE
    upper_clamped DOUBLE PRECISION;
    lower_clamped DOUBLE PRECISION;
BEGIN
    SELECT
        gtfs.clamp_shape_fraction(1.0000000000000002::DOUBLE PRECISION),
        gtfs.clamp_shape_fraction((-0.0000000000000002)::DOUBLE PRECISION)
    INTO upper_clamped, lower_clamped;

    IF upper_clamped <> 1.0::DOUBLE PRECISION
       OR lower_clamped <> 0.0::DOUBLE PRECISION THEN
        RAISE EXCEPTION
            'Expected endpoint clamps [1, 0], got [%, %]',
            upper_clamped,
            lower_clamped;
    END IF;
END;
$$;

-- Exercise delay-aware interpolation with a safe segment selected from the
-- currently installed VBB snapshot. The 120-second simulated TripUpdate delay
-- must appear in the estimated next-arrival result.
DO $$
DECLARE
    estimate_record RECORD;
BEGIN
    WITH candidate AS (
        SELECT
            stop_time.trip_id,
            stop_time.stop_sequence,
            stop_time.shape_fraction,
            next_stop.stop_sequence AS next_stop_sequence,
            next_stop.shape_fraction AS next_shape_fraction,
            (
                CURRENT_DATE
                + gtfs.gtfs_time_to_interval(stop_time.departure_time)
            ) AT TIME ZONE 'Europe/Berlin' AS departure_at,
            (
                CURRENT_DATE
                + gtfs.gtfs_time_to_interval(next_stop.arrival_time)
            ) AT TIME ZONE 'Europe/Berlin' AS next_arrival_at
        FROM gtfs.stop_times AS stop_time
        JOIN LATERAL (
            SELECT
                following.stop_sequence,
                following.shape_fraction,
                following.arrival_time
            FROM gtfs.stop_times AS following
            WHERE following.trip_id = stop_time.trip_id
              AND following.stop_sequence > stop_time.stop_sequence
            ORDER BY following.stop_sequence
            LIMIT 1
        ) AS next_stop ON TRUE
        WHERE next_stop.shape_fraction > stop_time.shape_fraction
          AND gtfs.gtfs_time_to_interval(next_stop.arrival_time)
              - gtfs.gtfs_time_to_interval(stop_time.departure_time)
              >= INTERVAL '2 minutes'
        ORDER BY stop_time.trip_id, stop_time.stop_sequence
        LIMIT 1
    )
    SELECT estimate.*
    INTO estimate_record
    FROM candidate
    CROSS JOIN LATERAL gtfs.estimate_trip_position(
        candidate.trip_id,
        CURRENT_DATE,
        candidate.departure_at + (candidate.next_arrival_at - candidate.departure_at) / 2,
        jsonb_build_array(
            jsonb_build_object(
                'stop_sequence', candidate.next_stop_sequence,
                'arrival_delay_seconds', 120
            )
        )
    ) AS estimate;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Expected a safe interpolable segment in the current VBB snapshot';
    END IF;

    IF estimate_record.delay_seconds <> 120
       OR estimate_record.is_estimated IS NOT TRUE
       OR estimate_record.position_status <> 'estimated_from_trip_update'
       OR estimate_record.longitude NOT BETWEEN 5.0 AND 20.0
       OR estimate_record.latitude NOT BETWEEN 45.0 AND 60.0
       OR estimate_record.speed_mps < 0.0 THEN
        RAISE EXCEPTION 'Unexpected estimated position result: %', row_to_json(estimate_record);
    END IF;
END;
$$;

SELECT 'Phase 2 local PostGIS validation: PASS' AS result;
