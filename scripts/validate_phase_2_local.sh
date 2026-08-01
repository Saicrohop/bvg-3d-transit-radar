#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_CONTAINER="$(docker ps --filter 'name=^/supabase_db_bvg-3d-radar$' --format '{{.Names}}')"
VALIDATION_SQL="$ROOT/scripts/validate_phase_2_local.sql"

if [[ -z "$DB_CONTAINER" ]]; then
    echo "Local Supabase database container is not running. Run: npm run supabase:start" >&2
    exit 1
fi

MSYS_NO_PATHCONV=1 docker exec -i "$DB_CONTAINER" psql -U postgres -d postgres \
    -v ON_ERROR_STOP=1 -f - < "$VALIDATION_SQL"
