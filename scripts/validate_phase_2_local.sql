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

-- A real VBB fixture that previously produced 1.0000000000000002. The clamp
-- must preserve its physical endpoint as exactly 1.0 before persistence.
DO $$
DECLARE
    raw_fraction DOUBLE PRECISION;
    clamped_fraction DOUBLE PRECISION;
BEGIN
    SELECT extensions.st_linelocatepoint(shape.geom_4326, stop.geom)
    INTO raw_fraction
    FROM gtfs.stop_times AS stop_time
    JOIN gtfs.trips AS trip ON trip.trip_id = stop_time.trip_id
    JOIN gtfs.stops AS stop ON stop.stop_id = stop_time.stop_id
    JOIN gtfs.route_shapes_geom AS shape ON shape.shape_id = trip.shape_id
    WHERE stop_time.trip_id = '288596537'
      AND stop_time.stop_id = 'de:12051:900275719::2'
      AND stop_time.stop_sequence = 32;

    IF raw_fraction IS NULL OR raw_fraction <= 1.0::DOUBLE PRECISION THEN
        RAISE EXCEPTION 'Regression fixture no longer reproduces an upper-bound projection: %', raw_fraction;
    END IF;

    SELECT gtfs.clamp_shape_fraction(raw_fraction) INTO clamped_fraction;

    IF clamped_fraction <> 1.0::DOUBLE PRECISION THEN
        RAISE EXCEPTION 'Expected a bounded shape fraction of 1.0, got %', clamped_fraction;
    END IF;
END;
$$;

-- Exercise delay-aware interpolation with static VBB data. The 120-second
-- simulated TripUpdate delay must appear in the estimated next-arrival result.
DO $$
DECLARE
    estimate_record RECORD;
BEGIN
    WITH scheduled AS (
        SELECT
            stop_time.trip_id,
            stop_time.stop_sequence,
            stop_time.shape_fraction,
            (
                DATE '2026-07-19'
                + gtfs.gtfs_time_to_interval(stop_time.departure_time)
            ) AT TIME ZONE 'Europe/Berlin' AS departure_at,
            LEAD(stop_time.stop_sequence) OVER stop_order AS next_stop_sequence,
            LEAD(stop_time.shape_fraction) OVER stop_order AS next_shape_fraction,
            LEAD(
                (
                    DATE '2026-07-19'
                    + gtfs.gtfs_time_to_interval(stop_time.arrival_time)
                ) AT TIME ZONE 'Europe/Berlin'
            ) OVER stop_order AS next_arrival_at
        FROM gtfs.stop_times AS stop_time
        WHERE stop_time.trip_id = '288596537'
        WINDOW stop_order AS (ORDER BY stop_time.stop_sequence)
    ),
    candidate AS (
        SELECT *
        FROM scheduled
        WHERE next_shape_fraction > shape_fraction
          AND next_arrival_at - departure_at >= INTERVAL '2 minutes'
        LIMIT 1
    )
    SELECT estimate.*
    INTO estimate_record
    FROM candidate
    CROSS JOIN LATERAL gtfs.estimate_trip_position(
        candidate.trip_id,
        DATE '2026-07-19',
        candidate.departure_at + (candidate.next_arrival_at - candidate.departure_at) / 2,
        jsonb_build_array(
            jsonb_build_object(
                'stop_sequence', candidate.next_stop_sequence,
                'arrival_delay_seconds', 120
            )
        )
    ) AS estimate;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Expected a safe interpolable segment for the VBB fixture';
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
