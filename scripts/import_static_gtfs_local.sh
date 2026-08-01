#!/usr/bin/env bash
# Import the currently supported VBB static GTFS export into local Supabase.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GTFS_DIR="$(cygpath -u "${1:-$ROOT/data/gtfs-static/GTFS}")"
DB_CONTAINER="$(docker ps --filter 'name=^/supabase_db_bvg-3d-radar$' --format '{{.Names}}')"
STAGING_DIR="/tmp/bvg-gtfs-import"
IMPORT_SQL="$ROOT/supabase/sql/phase_2_import_vbb_static_local.sql"
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

MSYS_NO_PATHCONV=1 docker exec "$DB_CONTAINER" sh -c \
    "rm -rf '$STAGING_DIR' && mkdir -p '$STAGING_DIR'"

for filename in routes.txt trips.txt stops.txt shapes.txt stop_times.txt; do
    source_path="$GTFS_DIR/$filename"
    destination_path="$STAGING_DIR/$filename"
    native_source_path="$(cygpath -w "$source_path")"

    MSYS_NO_PATHCONV=1 docker cp "$native_source_path" \
        "$DB_CONTAINER:$destination_path"

    host_sha256="$(sha256sum "$source_path" | awk '{print $1}')"
    container_sha256="$(MSYS_NO_PATHCONV=1 docker exec "$DB_CONTAINER" \
        sha256sum "$destination_path" | awk '{print $1}')"
    if [[ "$host_sha256" != "$container_sha256" ]]; then
        echo "Checksum mismatch after staging: $filename" >&2
        exit 1
    fi

done

MSYS_NO_PATHCONV=1 docker cp "$(cygpath -w "$IMPORT_SQL")" \
    "$DB_CONTAINER:$STAGING_DIR/import.sql"
MSYS_NO_PATHCONV=1 docker cp "$(cygpath -w "$PHASE_1_POST_IMPORT_SQL")" \
    "$DB_CONTAINER:$STAGING_DIR/phase_1_post_import.sql"
MSYS_NO_PATHCONV=1 docker cp "$(cygpath -w "$PHASE_2_POST_IMPORT_SQL")" \
    "$DB_CONTAINER:$STAGING_DIR/phase_2_post_import.sql"

echo "Importing VBB static GTFS into $DB_CONTAINER..."
MSYS_NO_PATHCONV=1 docker exec "$DB_CONTAINER" psql -U postgres -d postgres \
    -v ON_ERROR_STOP=1 -f "$STAGING_DIR/import.sql"

echo "Building route shape assets and Phase-1 indexes..."
MSYS_NO_PATHCONV=1 docker exec "$DB_CONTAINER" psql -U postgres -d postgres \
    -v ON_ERROR_STOP=1 -f "$STAGING_DIR/phase_1_post_import.sql"

echo "Projecting static stop times onto route shapes..."
MSYS_NO_PATHCONV=1 docker exec "$DB_CONTAINER" psql -U postgres -d postgres \
    -v ON_ERROR_STOP=1 -f "$STAGING_DIR/phase_2_post_import.sql"

echo "Local GTFS import and TripUpdate interpolation assets completed."
