-- PostGIS can return a normalized line fraction one IEEE-754 ULP beyond an
-- endpoint (for example 1.0000000000000002). Persisting the physical endpoint
-- as exactly 1.0 preserves the stop_times invariant and keeps downstream
-- ST_LineInterpolatePoint inputs in range.

CREATE OR REPLACE FUNCTION gtfs.clamp_shape_fraction(p_fraction DOUBLE PRECISION)
RETURNS DOUBLE PRECISION
LANGUAGE sql
IMMUTABLE
STRICT
PARALLEL SAFE
SET search_path = pg_catalog
AS $$
    SELECT CASE
        WHEN p_fraction > 1.0::DOUBLE PRECISION THEN 1.0::DOUBLE PRECISION
        WHEN p_fraction < 0.0::DOUBLE PRECISION THEN 0.0::DOUBLE PRECISION
        ELSE p_fraction
    END;
$$;

COMMENT ON FUNCTION gtfs.clamp_shape_fraction(DOUBLE PRECISION) IS
    'Bounds a PostGIS normalized line fraction to the closed [0, 1] interval before persistence.';

REVOKE ALL ON FUNCTION gtfs.clamp_shape_fraction(DOUBLE PRECISION)
    FROM PUBLIC, anon, authenticated;
