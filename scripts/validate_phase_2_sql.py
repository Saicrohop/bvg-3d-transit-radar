"""Static validation for the versioned Phase-2 TripUpdate interpolation SQL artifacts."""

from pathlib import Path

from pglast import parse_sql

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase/migrations/20260719110000_trip_update_interpolation.sql"
CLAMP_MIGRATION = ROOT / "supabase/migrations/20260719113000_clamp_stop_shape_fraction.sql"
LOCAL_IMPORT = ROOT / "supabase/sql/phase_2_import_vbb_static_local.sql"
POST_IMPORT = ROOT / "supabase/sql/phase_2_after_stop_times_import.sql"


def parse_psql_sql(file_path: Path) -> str:
    source = file_path.read_text(encoding="utf-8")
    parser_source = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("\\copy")
    )
    parse_sql(parser_source)
    return source.lower()


def require(source: str, fragment: str, file_path: Path) -> None:
    if fragment not in source:
        raise AssertionError(f"Missing required SQL fragment in {file_path}: {fragment}")


def main() -> None:
    migration = parse_psql_sql(MIGRATION)
    clamp_migration = parse_psql_sql(CLAMP_MIGRATION)
    local_import = parse_psql_sql(LOCAL_IMPORT)
    post_import = parse_psql_sql(POST_IMPORT)

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

    print("Phase 2 TripUpdate interpolation SQL validation: PASS")


if __name__ == "__main__":
    main()
