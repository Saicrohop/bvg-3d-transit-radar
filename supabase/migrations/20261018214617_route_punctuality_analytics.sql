BEGIN;

CREATE SCHEMA analytics;

CREATE TABLE analytics.route_observation_cycles (
    cycle_id uuid PRIMARY KEY,
    observed_at timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX route_observation_cycles_observed_at_idx
    ON analytics.route_observation_cycles (observed_at);

CREATE TABLE analytics.route_observation_windows (
    service_day date NOT NULL,
    bucket_start timestamptz NOT NULL,
    route_id text NOT NULL CHECK (btrim(route_id) <> ''),
    vehicle_category text NOT NULL CHECK (
        vehicle_category IN ('u_bahn', 's_bahn', 'bus', 'tram', 'regional', 'unknown')
    ),
    samples integer NOT NULL CHECK (samples > 0),
    on_time integer NOT NULL CHECK (on_time >= 0),
    late integer NOT NULL CHECK (late >= 0),
    sum_delay_seconds bigint NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (service_day, bucket_start, route_id, vehicle_category),
    CHECK (on_time + late = samples)
);
CREATE INDEX route_observation_windows_day_route_idx
    ON analytics.route_observation_windows (service_day, route_id);

CREATE TABLE analytics.route_daily_punctuality (
    service_day date NOT NULL,
    route_id text NOT NULL CHECK (btrim(route_id) <> ''),
    vehicle_category text NOT NULL CHECK (
        vehicle_category IN ('u_bahn', 's_bahn', 'bus', 'tram', 'regional', 'unknown')
    ),
    samples integer NOT NULL CHECK (samples > 0),
    on_time integer NOT NULL CHECK (on_time >= 0),
    late integer NOT NULL CHECK (late >= 0),
    sum_delay_seconds bigint NOT NULL,
    on_time_ratio numeric(7, 6) NOT NULL CHECK (on_time_ratio BETWEEN 0 AND 1),
    mean_delay_seconds numeric(12, 2) NOT NULL,
    computed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (service_day, route_id, vehicle_category),
    CHECK (on_time + late = samples)
);
CREATE INDEX route_daily_punctuality_ranking_idx
    ON analytics.route_daily_punctuality
       (service_day, on_time_ratio, mean_delay_seconds);

CREATE TABLE analytics.daily_line_ranking (
    service_day date NOT NULL,
    direction text NOT NULL CHECK (direction IN ('most_punctual', 'least_punctual')),
    position integer NOT NULL CHECK (position > 0),
    route_id text NOT NULL,
    vehicle_category text NOT NULL CHECK (
        vehicle_category IN ('u_bahn', 's_bahn', 'bus', 'tram', 'regional', 'unknown')
    ),
    samples integer NOT NULL CHECK (samples > 0),
    on_time_ratio numeric(7, 6) NOT NULL CHECK (on_time_ratio BETWEEN 0 AND 1),
    mean_delay_seconds numeric(12, 2) NOT NULL,
    computed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (service_day, direction, position),
    UNIQUE (service_day, direction, route_id, vehicle_category)
);

ALTER TABLE analytics.route_observation_cycles ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics.route_observation_windows ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics.route_daily_punctuality ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics.daily_line_ranking ENABLE ROW LEVEL SECURITY;

CREATE FUNCTION analytics.record_route_observations(
    p_cycle_id uuid,
    p_observed_at timestamptz,
    p_rows jsonb
) RETURNS boolean
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, analytics
AS $$
DECLARE
    inserted_cycles integer;
    service_day_value date;
    bucket_start_value timestamptz;
BEGIN
    IF p_cycle_id IS NULL OR p_observed_at IS NULL THEN
        RAISE EXCEPTION 'cycle_id and observed_at are required'
            USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(p_rows) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'observation rows must be a JSON array'
            USING ERRCODE = '22023';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM jsonb_to_recordset(p_rows) AS row_data(
            route_id text,
            vehicle_category text,
            samples integer,
            on_time integer,
            late integer,
            sum_delay_seconds bigint
        )
        WHERE row_data.route_id IS NULL
           OR btrim(row_data.route_id) = ''
           OR row_data.samples IS NULL
           OR row_data.samples <= 0
           OR row_data.on_time IS NULL
           OR row_data.on_time < 0
           OR row_data.late IS NULL
           OR row_data.late < 0
           OR row_data.on_time + row_data.late <> row_data.samples
           OR row_data.sum_delay_seconds IS NULL
           OR coalesce(nullif(btrim(row_data.vehicle_category), ''), 'unknown') NOT IN (
               'u_bahn', 's_bahn', 'bus', 'tram', 'regional', 'unknown'
           )
    ) THEN
        RAISE EXCEPTION 'invalid route punctuality observation row'
            USING ERRCODE = '22023';
    END IF;

    IF jsonb_array_length(p_rows) = 0 THEN
        RETURN false;
    END IF;

    -- Keep cycle IDs long enough to deduplicate database-commit/network-retry ambiguity.
    DELETE FROM analytics.route_observation_cycles
    WHERE observed_at < statement_timestamp() - interval '30 days';

    INSERT INTO analytics.route_observation_cycles (cycle_id, observed_at)
    VALUES (p_cycle_id, p_observed_at)
    ON CONFLICT (cycle_id) DO NOTHING;
    GET DIAGNOSTICS inserted_cycles = ROW_COUNT;
    IF inserted_cycles = 0 THEN
        RETURN false;
    END IF;

    service_day_value := (p_observed_at AT TIME ZONE 'Europe/Berlin')::date;
    bucket_start_value := date_bin(
        interval '15 minutes',
        p_observed_at,
        timestamptz '2000-01-01 00:00:00+00'
    );

    INSERT INTO analytics.route_observation_windows (
        service_day,
        bucket_start,
        route_id,
        vehicle_category,
        samples,
        on_time,
        late,
        sum_delay_seconds
    )
    SELECT
        service_day_value,
        bucket_start_value,
        btrim(row_data.route_id),
        coalesce(nullif(btrim(row_data.vehicle_category), ''), 'unknown'),
        sum(row_data.samples)::integer,
        sum(row_data.on_time)::integer,
        sum(row_data.late)::integer,
        sum(row_data.sum_delay_seconds)::bigint
    FROM jsonb_to_recordset(p_rows) AS row_data(
        route_id text,
        vehicle_category text,
        samples integer,
        on_time integer,
        late integer,
        sum_delay_seconds bigint
    )
    GROUP BY btrim(row_data.route_id),
             coalesce(nullif(btrim(row_data.vehicle_category), ''), 'unknown')
    ON CONFLICT (service_day, bucket_start, route_id, vehicle_category)
    DO UPDATE SET
        samples = analytics.route_observation_windows.samples + EXCLUDED.samples,
        on_time = analytics.route_observation_windows.on_time + EXCLUDED.on_time,
        late = analytics.route_observation_windows.late + EXCLUDED.late,
        sum_delay_seconds = analytics.route_observation_windows.sum_delay_seconds
            + EXCLUDED.sum_delay_seconds,
        updated_at = now();

    RETURN true;
END;
$$;

CREATE FUNCTION analytics.refresh_route_daily_punctuality(p_service_day date)
RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, analytics
AS $$
DECLARE
    affected_rows integer;
BEGIN
    IF p_service_day IS NULL THEN
        RAISE EXCEPTION 'service_day is required' USING ERRCODE = '22023';
    END IF;

    DELETE FROM analytics.route_daily_punctuality
    WHERE service_day = p_service_day;

    INSERT INTO analytics.route_daily_punctuality (
        service_day,
        route_id,
        vehicle_category,
        samples,
        on_time,
        late,
        sum_delay_seconds,
        on_time_ratio,
        mean_delay_seconds
    )
    SELECT
        windows.service_day,
        windows.route_id,
        windows.vehicle_category,
        sum(windows.samples)::integer,
        sum(windows.on_time)::integer,
        sum(windows.late)::integer,
        sum(windows.sum_delay_seconds)::bigint,
        round(sum(windows.on_time)::numeric / sum(windows.samples), 6),
        round(sum(windows.sum_delay_seconds)::numeric / sum(windows.samples), 2)
    FROM analytics.route_observation_windows AS windows
    WHERE windows.service_day = p_service_day
    GROUP BY windows.service_day, windows.route_id, windows.vehicle_category;

    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    RETURN affected_rows;
END;
$$;

CREATE FUNCTION analytics.refresh_daily_line_ranking(
    p_service_day date,
    p_min_samples integer DEFAULT 40,
    p_limit integer DEFAULT 10
) RETURNS TABLE (
    direction text,
    rank_position integer,
    route_id text,
    vehicle_category text,
    samples integer,
    on_time_ratio numeric,
    mean_delay_seconds numeric
)
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, analytics
AS $$
BEGIN
    IF p_service_day IS NULL OR p_min_samples <= 0 OR p_limit <= 0 OR p_limit > 100 THEN
        RAISE EXCEPTION 'invalid daily ranking parameters'
            USING ERRCODE = '22023';
    END IF;

    DELETE FROM analytics.daily_line_ranking AS ranking
    WHERE ranking.service_day = p_service_day;

    WITH qualified AS (
        SELECT daily.route_id,
               daily.vehicle_category,
               daily.samples,
               daily.on_time_ratio,
               daily.mean_delay_seconds
        FROM analytics.route_daily_punctuality AS daily
        WHERE daily.service_day = p_service_day
          AND daily.samples >= p_min_samples
    ),
    most_ranked AS (
        SELECT row_number() OVER (
                   ORDER BY qualified.on_time_ratio DESC,
                            qualified.mean_delay_seconds ASC,
                            qualified.route_id,
                            qualified.vehicle_category
               )::integer AS rank_position,
               qualified.*
        FROM qualified
    ),
    least_ranked AS (
        SELECT row_number() OVER (
                   ORDER BY qualified.on_time_ratio ASC,
                            qualified.mean_delay_seconds DESC,
                            qualified.route_id,
                            qualified.vehicle_category
               )::integer AS rank_position,
               qualified.*
        FROM qualified
    )
    INSERT INTO analytics.daily_line_ranking (
        service_day,
        direction,
        position,
        route_id,
        vehicle_category,
        samples,
        on_time_ratio,
        mean_delay_seconds
    )
    SELECT p_service_day,
           ranked.direction,
           ranked.rank_position,
           ranked.route_id,
           ranked.vehicle_category,
           ranked.samples,
           ranked.on_time_ratio,
           ranked.mean_delay_seconds
    FROM (
        SELECT 'most_punctual'::text AS direction,
               most.rank_position,
               most.route_id,
               most.vehicle_category,
               most.samples,
               most.on_time_ratio,
               most.mean_delay_seconds
        FROM most_ranked AS most
        WHERE most.rank_position <= p_limit

        UNION ALL

        SELECT 'least_punctual'::text AS direction,
               least.rank_position,
               least.route_id,
               least.vehicle_category,
               least.samples,
               least.on_time_ratio,
               least.mean_delay_seconds
        FROM least_ranked AS least
        WHERE least.rank_position <= p_limit
    ) AS ranked;

    RETURN QUERY
    SELECT ranking.direction,
           ranking.position,
           ranking.route_id,
           ranking.vehicle_category,
           ranking.samples,
           ranking.on_time_ratio,
           ranking.mean_delay_seconds
    FROM analytics.daily_line_ranking AS ranking
    WHERE ranking.service_day = p_service_day
    ORDER BY ranking.direction, ranking.position;
END;
$$;

REVOKE ALL ON SCHEMA analytics FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA analytics TO service_role;
REVOKE ALL ON ALL TABLES IN SCHEMA analytics FROM PUBLIC, anon, authenticated;
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO service_role;
REVOKE ALL ON FUNCTION analytics.record_route_observations(uuid, timestamptz, jsonb)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION analytics.refresh_route_daily_punctuality(date)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION analytics.refresh_daily_line_ranking(date, integer, integer)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION analytics.record_route_observations(uuid, timestamptz, jsonb)
    TO service_role;
GRANT EXECUTE ON FUNCTION analytics.refresh_route_daily_punctuality(date)
    TO service_role;
GRANT EXECUTE ON FUNCTION analytics.refresh_daily_line_ranking(date, integer, integer)
    TO service_role;

COMMIT;
