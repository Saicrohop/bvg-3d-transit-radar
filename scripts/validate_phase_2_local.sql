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

    IF upper_clamped IS DISTINCT FROM 1.0::DOUBLE PRECISION
       OR lower_clamped IS DISTINCT FROM 0.0::DOUBLE PRECISION THEN
        RAISE EXCEPTION
            'Expected endpoint clamps [1, 0], got [%, %]',
            upper_clamped,
            lower_clamped;
    END IF;
END;
$$;

-- Exercise all timing-evidence modes with one safe segment selected from the
-- currently installed VBB snapshot. Schedule-only interpolation may render a
-- marker but must not manufacture an observed zero delay.
DO $$
DECLARE
    candidate_record RECORD;
    schedule_only_record RECORD;
    realtime_delay_record RECORD;
    absolute_time_record RECORD;
    batch_result_count BIGINT;
    batch_schedule_only_count BIGINT;
    batch_realtime_delay_count BIGINT;
    batch_route_metadata_count BIGINT;
BEGIN
    SELECT
        stop_time.trip_id,
        next_stop.stop_sequence AS next_stop_sequence,
        (
            CURRENT_DATE
            + gtfs.gtfs_time_to_interval(stop_time.departure_time)
        ) AT TIME ZONE 'Europe/Berlin' AS departure_at,
        (
            CURRENT_DATE
            + gtfs.gtfs_time_to_interval(next_stop.arrival_time)
        ) AT TIME ZONE 'Europe/Berlin' AS next_arrival_at
    INTO candidate_record
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
    WHERE stop_time.shape_fraction IS NOT NULL
      AND next_stop.shape_fraction > stop_time.shape_fraction
      AND gtfs.gtfs_time_to_interval(next_stop.arrival_time)
          - gtfs.gtfs_time_to_interval(stop_time.departure_time)
          >= INTERVAL '2 minutes'
    ORDER BY stop_time.trip_id, stop_time.stop_sequence
    LIMIT 1;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Expected a safe interpolable segment in the current VBB snapshot';
    END IF;

    SELECT estimate.*
    INTO schedule_only_record
    FROM gtfs.estimate_trip_position(
        candidate_record.trip_id,
        CURRENT_DATE,
        candidate_record.departure_at
            + (candidate_record.next_arrival_at - candidate_record.departure_at) / 2,
        '[]'::JSONB
    ) AS estimate;

    IF NOT FOUND
       OR schedule_only_record.delay_seconds IS NOT NULL
       OR schedule_only_record.timing_source IS DISTINCT FROM 'schedule_only'
       OR schedule_only_record.is_estimated IS NOT TRUE THEN
        RAISE EXCEPTION
            'Schedule-only interpolation claimed realtime evidence: %',
            row_to_json(schedule_only_record);
    END IF;

    SELECT estimate.*
    INTO realtime_delay_record
    FROM gtfs.estimate_trip_position(
        candidate_record.trip_id,
        CURRENT_DATE,
        candidate_record.departure_at
            + (candidate_record.next_arrival_at - candidate_record.departure_at) / 2,
        jsonb_build_array(
            jsonb_build_object(
                'stop_sequence', candidate_record.next_stop_sequence,
                'arrival_delay_seconds', 120
            )
        )
    ) AS estimate;

    IF NOT FOUND
       OR realtime_delay_record.delay_seconds IS DISTINCT FROM 120
       OR realtime_delay_record.timing_source IS DISTINCT FROM 'realtime_delay'
       OR realtime_delay_record.is_estimated IS NOT TRUE
       OR realtime_delay_record.position_status IS DISTINCT FROM 'estimated_from_trip_update'
       OR realtime_delay_record.longitude IS NULL
       OR realtime_delay_record.longitude NOT BETWEEN 5.0 AND 20.0
       OR realtime_delay_record.latitude IS NULL
       OR realtime_delay_record.latitude NOT BETWEEN 45.0 AND 60.0
       OR realtime_delay_record.speed_mps IS NULL
       OR realtime_delay_record.speed_mps < 0.0 THEN
        RAISE EXCEPTION
            'Unexpected explicit-delay position result: %',
            row_to_json(realtime_delay_record);
    END IF;

    SELECT estimate.*
    INTO absolute_time_record
    FROM gtfs.estimate_trip_position(
        candidate_record.trip_id,
        CURRENT_DATE,
        candidate_record.departure_at
            + (candidate_record.next_arrival_at - candidate_record.departure_at) / 2,
        jsonb_build_array(
            jsonb_build_object(
                'stop_sequence', candidate_record.next_stop_sequence,
                'arrival_time', EXTRACT(
                    EPOCH FROM candidate_record.next_arrival_at + INTERVAL '90 seconds'
                )::BIGINT
            )
        )
    ) AS estimate;

    IF NOT FOUND
       OR absolute_time_record.delay_seconds IS DISTINCT FROM 90
       OR absolute_time_record.timing_source IS DISTINCT FROM 'absolute_realtime_time' THEN
        RAISE EXCEPTION
            'Unexpected absolute-time position result: %',
            row_to_json(absolute_time_record);
    END IF;

    SELECT
        COUNT(*),
        COUNT(*) FILTER (
            WHERE batch.input_index = 0
              AND batch.delay_seconds IS NULL
              AND batch.timing_source = 'schedule_only'
        ),
        COUNT(*) FILTER (
            WHERE batch.input_index = 1
              AND batch.delay_seconds = 120
              AND batch.timing_source = 'realtime_delay'
        ),
        COUNT(*) FILTER (WHERE batch.route_type IS NOT NULL)
    INTO
        batch_result_count,
        batch_schedule_only_count,
        batch_realtime_delay_count,
        batch_route_metadata_count
    FROM gtfs.estimate_trip_positions_batch(
        candidate_record.departure_at
            + (candidate_record.next_arrival_at - candidate_record.departure_at) / 2,
        jsonb_build_array(
            jsonb_build_object(
                'trip_id', candidate_record.trip_id,
                'service_date', CURRENT_DATE::TEXT,
                'stop_time_updates', '[]'::JSONB
            ),
            jsonb_build_object(
                'trip_id', candidate_record.trip_id,
                'service_date', CURRENT_DATE::TEXT,
                'stop_time_updates', jsonb_build_array(
                    jsonb_build_object(
                        'stop_sequence', candidate_record.next_stop_sequence,
                        'arrival_delay_seconds', 120
                    )
                )
            )
        )
    ) AS batch;

    IF batch_result_count IS DISTINCT FROM 2
       OR batch_schedule_only_count IS DISTINCT FROM 1
       OR batch_realtime_delay_count IS DISTINCT FROM 1
       OR batch_route_metadata_count IS DISTINCT FROM 2 THEN
        RAISE EXCEPTION
            'Unexpected batch interpolation result: total=%, schedule_only=%, realtime_delay=%, route_metadata=%',
            batch_result_count,
            batch_schedule_only_count,
            batch_realtime_delay_count,
            batch_route_metadata_count;
    END IF;
END;
$$;

-- The estimator is backend-only. Browser roles must not gain EXECUTE through
-- either direct grants or PUBLIC, while service_role must retain it.
DO $$
DECLARE
    single_function_signature TEXT :=
        'gtfs.estimate_trip_position(text,date,timestamptz,jsonb)';
    batch_function_signature TEXT :=
        'gtfs.estimate_trip_positions_batch(timestamptz,jsonb)';
BEGIN
    IF has_function_privilege('anon', single_function_signature, 'EXECUTE')
       OR has_function_privilege('authenticated', single_function_signature, 'EXECUTE')
       OR NOT has_function_privilege('service_role', single_function_signature, 'EXECUTE')
       OR has_function_privilege('anon', batch_function_signature, 'EXECUTE')
       OR has_function_privilege('authenticated', batch_function_signature, 'EXECUTE')
       OR NOT has_function_privilege('service_role', batch_function_signature, 'EXECUTE') THEN
        RAISE EXCEPTION 'Unexpected position-estimator EXECUTE privileges';
    END IF;
END;
$$;

SELECT 'Phase 2 local PostGIS validation: PASS' AS result;
