"""Static validation for the versioned Phase-1 PostGIS SQL artifacts."""

from pathlib import Path

from pglast import parse_sql

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase/migrations/20260717163000_gtfs_static_postgis.sql"
POST_IMPORT = ROOT / "supabase/sql/phase_1_after_static_gtfs_import.sql"
LOCAL_IMPORT = ROOT / "supabase/sql/phase_1_import_vbb_static_local.sql"


def require(source: str, fragment: str, file_path: Path) -> None:
    if fragment not in source.lower():
        raise AssertionError(f"Missing required SQL fragment in {file_path}: {fragment}")


def main() -> None:
    sources: dict[Path, str] = {}
    for file_path in (MIGRATION, POST_IMPORT, LOCAL_IMPORT):
        source = file_path.read_text(encoding="utf-8")
        parser_source = "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith("\\copy")
        )
        parse_sql(parser_source)
        sources[file_path] = source

    migration = sources[MIGRATION]
    post_import = sources[POST_IMPORT]
    local_import = sources[LOCAL_IMPORT]

    for fragment in (
        "create extension if not exists postgis with schema extensions;",
        "create schema if not exists gtfs;",
        "create table if not exists gtfs.routes",
        "create table if not exists gtfs.trips",
        "create table if not exists gtfs.stops",
        "create table if not exists gtfs.shapes",
        "extensions.geometry(point, 4326)",
        "generated always as",
        "order by shape_pt_sequence",
        "st_transform(geom_4326, 25833)",
        "create materialized view if not exists gtfs.route_shapes_geom",
        "with no data;",
        "alter table gtfs.routes enable row level security;",
        "revoke all on schema gtfs from public;",
    ):
        require(migration, fragment, MIGRATION)

    for fragment in (
        "refresh materialized view gtfs.route_shapes_geom;",
        "on gtfs.stops using gist (geom);",
        "create unique index if not exists route_shapes_geom_shape_id_key",
        "invalid_wgs84_shape_lines",
    ):
        require(post_import, fragment, POST_IMPORT)

    for fragment in (
        "truncate table gtfs.trips, gtfs.shapes, gtfs.stops, gtfs.routes;",
        "\\copy gtfs.routes",
        "\\copy gtfs.stops",
        "\\copy gtfs.shapes",
        "\\copy gtfs.trips",
        "header true",
        "commit;",
    ):
        require(local_import, fragment, LOCAL_IMPORT)

    print("Phase 1 static SQL validation: PASS")


if __name__ == "__main__":
    main()
