"""Static validation for the versioned Phase-2 TripUpdate interpolation SQL artifacts."""

from pathlib import Path

from pglast import parse_sql

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase/migrations/20260719110000_trip_update_interpolation.sql"
CLAMP_MIGRATION = (
    ROOT / "supabase/migrations/20260719113000_clamp_stop_shape_fraction.sql"
)
TIMING_EVIDENCE_MIGRATION = (
    ROOT / "supabase/migrations/20260902223000_trip_update_timing_evidence.sql"
)
BATCH_ESTIMATION_MIGRATION = (
    ROOT / "supabase/migrations/20260909050337_batch_trip_position_estimation.sql"
)
SET_BASED_BATCH_MIGRATION = (
    ROOT
    / "supabase/migrations/20260909052610_set_based_batch_trip_position_estimation.sql"
)
OPTIMIZED_BATCH_MIGRATION = (
    ROOT / "supabase/migrations/20260909054609_optimize_batch_dynamic_updates.sql"
)
LOCAL_IMPORT = ROOT / "supabase/sql/phase_2_import_vbb_static_local.sql"
POST_IMPORT = ROOT / "supabase/sql/phase_2_after_stop_times_import.sql"
LOCAL_VALIDATION = ROOT / "scripts/validate_phase_2_local.sql"


def parse_psql_sql(file_path: Path) -> str:
    source = file_path.read_text(encoding="utf-8")
    parser_source = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("\\copy")
    )
    parse_sql(parser_source)
    return source.lower()


def require(source: str, fragment: str, file_path: Path) -> None:
    if fragment not in source:
        raise AssertionError(
            f"Missing required SQL fragment in {file_path}: {fragment}"
        )


def forbid(source: str, fragment: str, file_path: Path) -> None:
    if fragment in source:
        raise AssertionError(f"Forbidden SQL fragment in {file_path}: {fragment}")


def main() -> None:
    migration = parse_psql_sql(MIGRATION)
    clamp_migration = parse_psql_sql(CLAMP_MIGRATION)
    timing_evidence_migration = parse_psql_sql(TIMING_EVIDENCE_MIGRATION)
    batch_estimation_migration = parse_psql_sql(BATCH_ESTIMATION_MIGRATION)
    set_based_batch_migration = parse_psql_sql(SET_BASED_BATCH_MIGRATION)
    optimized_batch_migration = parse_psql_sql(OPTIMIZED_BATCH_MIGRATION)
    local_import = parse_psql_sql(LOCAL_IMPORT)
    post_import = parse_psql_sql(POST_IMPORT)
    local_validation = parse_psql_sql(LOCAL_VALIDATION)

    for fragment in (
        "create table if not exists gtfs.stop_times",
        "primary key (trip_id, stop_sequence)",
        "foreign key (trip_id) references gtfs.trips",
        "foreign key (stop_id) references gtfs.stops",
        "shape_fraction",
        "create or replace function gtfs.gtfs_time_to_interval",
        "create or replace function gtfs.estimate_trip_position",
        "extensions.st_lineinterpolatepoint",
        "extensions.st_azimuth",
        "at time zone 'europe/berlin'",
        "alter table gtfs.stop_times enable row level security",
        "revoke all on function gtfs.estimate_trip_position",
    ):
        require(migration, fragment, MIGRATION)

    for fragment in (
        "create or replace function gtfs.clamp_shape_fraction",
        "case",
        "when p_fraction > 1.0::double precision then 1.0::double precision",
        "when p_fraction < 0.0::double precision then 0.0::double precision",
        "revoke all on function gtfs.clamp_shape_fraction",
    ):
        require(clamp_migration, fragment, CLAMP_MIGRATION)

    for fragment in (
        "drop function gtfs.estimate_trip_position(text, date, timestamptz, jsonb)",
        "create function gtfs.estimate_trip_position",
        "delay_seconds integer",
        "timing_source text",
        "'absolute_realtime_time'",
        "'realtime_delay'",
        "'schedule_only'",
        "when point.next_arrival_timing_source = 'schedule_only' then null",
        "revoke all on function gtfs.estimate_trip_position",
        "grant execute on function gtfs.estimate_trip_position",
    ):
        require(timing_evidence_migration, fragment, TIMING_EVIDENCE_MIGRATION)

    for fragment in (
        "create function gtfs.estimate_trip_positions_batch",
        "jsonb_array_elements(",
        "coalesce(p_updates, '[]'::jsonb)",
        "with ordinality",
        "cross join lateral gtfs.estimate_trip_position",
        "left join gtfs.routes as route",
        "order by batch_input.input_index",
        "revoke all on function gtfs.estimate_trip_positions_batch",
        "grant execute on function gtfs.estimate_trip_positions_batch",
    ):
        require(batch_estimation_migration, fragment, BATCH_ESTIMATION_MIGRATION)

    for fragment in (
        "create or replace function gtfs.estimate_trip_positions_batch",
        "partition by estimated.input_index",
        "row_number() over",
        "partition by active.input_index",
        "join gtfs.stop_times as stop_time",
        "left join gtfs.routes as route",
        "where ranked.segment_rank = 1",
    ):
        require(set_based_batch_migration, fragment, SET_BASED_BATCH_MIGRATION)
    forbid(
        set_based_batch_migration,
        "cross join lateral gtfs.estimate_trip_position",
        SET_BASED_BATCH_MIGRATION,
    )

    for fragment in (
        "create or replace function gtfs.estimate_trip_positions_batch",
        "sequence_updates as",
        "stop_id_updates as",
        "left join sequence_updates as sequence_dynamic",
        "left join stop_id_updates as stop_id_dynamic",
        "when sequence_dynamic.update_ordinal is not null",
        "partition by estimated.input_index",
        "partition by active.input_index",
    ):
        require(optimized_batch_migration, fragment, OPTIMIZED_BATCH_MIGRATION)
    forbid(
        optimized_batch_migration,
        "left join lateral",
        OPTIMIZED_BATCH_MIGRATION,
    )

    for fragment in (
        "truncate table gtfs.stop_times, gtfs.trips, gtfs.shapes, gtfs.stops, gtfs.routes;",
        "\\copy gtfs.stop_times",
        "header true",
        "commit;",
    ):
        require(local_import, fragment, LOCAL_IMPORT)

    for fragment in (
        "update gtfs.stop_times as stop_time",
        "gtfs.clamp_shape_fraction",
        "extensions.st_linelocatepoint",
        "create index if not exists stop_times_stop_id_idx",
        "analyze gtfs.stop_times",
    ):
        require(post_import, fragment, POST_IMPORT)

    for fragment in (
        "schedule_only_record.timing_source is distinct from 'schedule_only'",
        "upper_clamped is distinct from 1.0::double precision",
        "lower_clamped is distinct from 0.0::double precision",
        "realtime_delay_record.delay_seconds is distinct from 120",
        "realtime_delay_record.timing_source is distinct from 'realtime_delay'",
        "realtime_delay_record.position_status is distinct from 'estimated_from_trip_update'",
        "realtime_delay_record.longitude is null",
        "realtime_delay_record.latitude is null",
        "realtime_delay_record.speed_mps is null",
        "absolute_time_record.delay_seconds is distinct from 90",
        "absolute_time_record.timing_source is distinct from 'absolute_realtime_time'",
        "gtfs.estimate_trip_positions_batch(",
        "batch_result_count is distinct from 2",
        "batch_schedule_only_count is distinct from 1",
        "batch_realtime_delay_count is distinct from 1",
        "batch_route_metadata_count is distinct from 2",
        "has_function_privilege('anon'",
        "has_function_privilege('authenticated'",
        "has_function_privilege('service_role'",
    ):
        require(local_validation, fragment, LOCAL_VALIDATION)

    print("Phase 2 TripUpdate interpolation SQL validation: PASS")


if __name__ == "__main__":
    main()
