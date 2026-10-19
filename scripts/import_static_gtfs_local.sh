#!/usr/bin/env bash
# Import the currently supported VBB static GTFS export into local Supabase.
# Maintenance operation: pause the worker first; readers can block on table locks.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GTFS_DIR="$(cygpath -u "${1:-$ROOT/data/gtfs-static/GTFS}")"
DB_CONTAINER="$(docker ps --filter 'name=^/supabase_db_bvg-3d-radar$' --format '{{.Names}}')"
IMPORT_SQL="$ROOT/supabase/sql/phase_2_import_vbb_static_atomic_local.sql"
PHASE_1_POST_IMPORT_SQL="$ROOT/supabase/sql/phase_1_after_static_gtfs_import.sql"
PHASE_2_POST_IMPORT_SQL="$ROOT/supabase/sql/phase_2_after_stop_times_import.sql"

if [[ -z "$DB_CONTAINER" ]]; then
    echo "Local Supabase database container is not running. Run: npm run supabase:start" >&2
    exit 1
fi

if [[ ! -d "$GTFS_DIR" ]]; then
    echo "GTFS directory not found: $GTFS_DIR" >&2
    exit 1
fi

# The Hermes Python launcher is native Windows Python, so pass native paths
# rather than MSYS /c/... paths to it.
python "$(cygpath -w "$ROOT/scripts/validate_vbb_gtfs_static.py")" \
    "$(cygpath -w "$GTFS_DIR")"

# Isolated staging prevents two invocations from replacing each other's input.
STAGING_DIR="$(MSYS_NO_PATHCONV=1 docker exec "$DB_CONTAINER" \
    mktemp -d /tmp/bvg-gtfs-import.XXXXXXXX)"
cleanup() {
    MSYS_NO_PATHCONV=1 docker exec "$DB_CONTAINER" \
        rm -rf -- "$STAGING_DIR" || true
}
trap cleanup EXIT

for filename in routes.txt trips.txt stops.txt shapes.txt stop_times.txt; do
    source_path="$GTFS_DIR/$filename"
    destination_path="$STAGING_DIR/$filename"
    native_source_path="$(cygpath -w "$source_path")"

    MSYS_NO_PATHCONV=1 docker cp "$native_source_path" \
        "$DB_CONTAINER:$destination_path"

    host_checksum="$(sha256sum "$source_path")"
    read -r host_sha256 _ <<< "$host_checksum"
    container_checksum="$(MSYS_NO_PATHCONV=1 docker exec "$DB_CONTAINER" \
        sha256sum "$destination_path")"
    read -r container_sha256 _ <<< "$container_checksum"
    if [[ "$host_sha256" != "$container_sha256" ]]; then
        echo "Checksum mismatch after staging: $filename" >&2
        exit 1
    fi

done

for sql_file in "$IMPORT_SQL" "$PHASE_1_POST_IMPORT_SQL" "$PHASE_2_POST_IMPORT_SQL"; do
    MSYS_NO_PATHCONV=1 docker cp "$(cygpath -w "$sql_file")" \
        "$DB_CONTAINER:$STAGING_DIR/$(basename "$sql_file")"
done

echo "Importing VBB tables, refreshing shapes, projecting stops and checking health atomically..."
MSYS_NO_PATHCONV=1 docker exec -w "$STAGING_DIR" "$DB_CONTAINER" \
    psql -X -U postgres -d postgres --single-transaction \
    -v ON_ERROR_STOP=1 -f "$STAGING_DIR/$(basename "$IMPORT_SQL")"

echo "Local GTFS import and TripUpdate interpolation assets committed after health gate."
