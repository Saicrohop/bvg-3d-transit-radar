-- Regression test for an observed PostGIS boundary condition.
--
-- ST_LineLocatePoint can return one IEEE-754 ULP above 1.0 for an endpoint.
-- The static import must clamp that value before writing it to the constrained
-- gtfs.stop_times.shape_fraction column.

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
