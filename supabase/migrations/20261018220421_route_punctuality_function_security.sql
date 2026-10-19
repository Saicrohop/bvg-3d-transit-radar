BEGIN;

-- The routines accept validated, schema-qualified data only and pin search_path;
-- SECURITY DEFINER lets the restricted service_role execute writes without
-- granting it direct mutation access to analytics tables.
ALTER FUNCTION analytics.record_route_observations(uuid, timestamptz, jsonb)
    SECURITY DEFINER;
ALTER FUNCTION analytics.record_route_observations(uuid, timestamptz, jsonb)
    SET search_path = pg_catalog, analytics;

ALTER FUNCTION analytics.refresh_route_daily_punctuality(date)
    SECURITY DEFINER;
ALTER FUNCTION analytics.refresh_route_daily_punctuality(date)
    SET search_path = pg_catalog, analytics;

ALTER FUNCTION analytics.refresh_daily_line_ranking(date, integer, integer)
    SECURITY DEFINER;
ALTER FUNCTION analytics.refresh_daily_line_ranking(date, integer, integer)
    SET search_path = pg_catalog, analytics;

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
