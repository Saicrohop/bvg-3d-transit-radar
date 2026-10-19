"""Offline source-contract checks; never execute importer, Docker or PostgreSQL."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "supabase" / "sql"
ORCHESTRATOR = SQL_DIR / "phase_2_import_vbb_static_atomic_local.sql"
SHELL = ROOT / "scripts" / "import_static_gtfs_local.sh"


def executable_sql(path):
    # Only these controlled source scripts are accepted; -- comments must not
    # make future CONCURRENTLY suggestions look like executable statements.
    return re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))


def test_import_uses_one_fail_closed_transaction_through_shape_projection():
    shell = SHELL.read_text(encoding="utf-8")
    assert len(re.findall(r"\bpsql\s", shell)) == 1
    assert "--single-transaction" in shell
    assert "ON_ERROR_STOP=1" in shell
    assert "-X" in shell  # Ignore user/container psqlrc (including error rollback).
    assert ORCHESTRATOR.name in shell
    assert ORCHESTRATOR.exists(), "Atomic orchestrator is missing"
    sql = executable_sql(ORCHESTRATOR)
    assert not re.search(r"\b(BEGIN|COMMIT|ROLLBACK)\s*;", sql, re.I)
    assert "phase_2_import_vbb_static_local.sql" not in sql
    assert "\\ir phase_1_after_static_gtfs_import.sql" in sql
    assert "\\ir phase_2_after_stop_times_import.sql" in sql
    assert sql.index("TRUNCATE TABLE") < sql.index("\\copy gtfs.routes")
    assert sql.index("\\copy gtfs.stop_times") < sql.index("\\ir phase_1_after")
    assert sql.index("\\ir phase_1_after") < sql.index("\\ir phase_2_after")
    assert sql.index("\\ir phase_2_after") < sql.index("DO $health$")
    assert "RAISE EXCEPTION" in sql[sql.index("DO $health$"):]


def test_reused_derivation_scripts_are_transaction_safe():
    for filename in ["phase_1_after_static_gtfs_import.sql", "phase_2_after_stop_times_import.sql"]:
        sql = executable_sql(SQL_DIR / filename)
        assert not re.search(r"\b(BEGIN|COMMIT|ROLLBACK|CONCURRENTLY|VACUUM)\b", sql, re.I)
    assert "REFRESH MATERIALIZED VIEW gtfs.route_shapes_geom;" in executable_sql(
        SQL_DIR / "phase_1_after_static_gtfs_import.sql"
    )
    assert "SET shape_fraction = gtfs.clamp_shape_fraction(" in executable_sql(
        SQL_DIR / "phase_2_after_stop_times_import.sql"
    )


def test_atomic_copy_columns_and_filenames_match_supported_legacy_export():
    assert ORCHESTRATOR.exists()
    pattern = r"\\copy (gtfs\.\w+) \(([^)]+)\) FROM '([^']+)' WITH ([^\n]+)"
    legacy = re.findall(pattern, executable_sql(SQL_DIR / "phase_2_import_vbb_static_local.sql"))
    atomic = re.findall(pattern, executable_sql(ORCHESTRATOR))
    assert len(legacy) == len(atomic) == 5
    assert [(table, columns, Path(path).name, options) for table, columns, path, options in legacy] == atomic


def test_isolated_staging_and_relative_includes_stay_aligned():
    shell = SHELL.read_text(encoding="utf-8")
    assert "mktemp -d /tmp/bvg-gtfs-import.XXXXXXXX" in shell
    assert 'docker exec -w "$STAGING_DIR"' in shell
    assert 'trap cleanup EXIT' in shell
    assert '$(basename "$sql_file")' in shell
    assert not re.search(r"rm -rf\s+'?/tmp/bvg-gtfs-import'?\s", shell)
    sql = executable_sql(ORCHESTRATOR)
    assert set(re.findall(r"^\\ir (\S+)$", sql, re.M)) == {
        "phase_1_after_static_gtfs_import.sql", "phase_2_after_stop_times_import.sql"
    }
    assert all((SQL_DIR / name).is_file() for name in re.findall(r"^\\ir (\S+)$", sql, re.M))


def test_health_gate_is_after_derivation_and_does_not_call_writing_estimators():
    sql = executable_sql(ORCHESTRATOR)
    assert "SET LOCAL lock_timeout = '5s';" in sql
    assert "pg_try_advisory_xact_lock" in sql
    gate = sql[sql.index("DO $health$"):]
    for table in ["routes", "trips", "stops", "shapes", "stop_times", "route_shapes_geom"]:
        assert f"FROM gtfs.{table}" in gate
    assert "HAVING COUNT(*) >= 2" in gate
    assert "st_isvalid(geom_4326)" in gate
    assert "st_isvalid(geom_25833)" in gate
    assert "shape_fraction IS NULL" in gate
    assert "shape_fraction BETWEEN 0.0 AND 1.0" in gate
    assert gate.count("RAISE EXCEPTION") == 5
    assert "estimate_trip" not in gate
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|CREATE|ALTER|GRANT|REVOKE)\b", gate, re.I)
