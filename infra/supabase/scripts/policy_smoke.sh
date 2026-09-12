#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_SQL="${SCRIPT_DIR}/../tests/policy_smoke.sql"

command -v psql >/dev/null 2>&1 || {
  echo "psql is required." >&2
  exit 127
}

# PGDATABASE accepts a full libpq URI. Keeping it in the environment avoids
# placing administrator credentials in process arguments.
export PGDATABASE="${SUPABASE_DB_ADMIN_URL:-postgresql://postgres:postgres@127.0.0.1:54322/postgres}"

psql \
  --no-psqlrc \
  --set=ON_ERROR_STOP=1 \
  --file="${TEST_SQL}"
