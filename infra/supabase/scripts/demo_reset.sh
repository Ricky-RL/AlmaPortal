#!/usr/bin/env bash
set -euo pipefail

CONFIRMATION="RESET-LOCAL-DEMO"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [[ "${1:-}" != "--apply" ]]; then
  cat <<EOF
Dry run: this would reset the local AlmaPortal Supabase database, reapply every
migration, and run the intentionally empty seed.sql.

No remote project is accepted by this script.

To apply:
  $(basename "$0") --apply --confirm ${CONFIRMATION}
EOF
  exit 0
fi

if [[ "${2:-}" != "--confirm" || "${3:-}" != "${CONFIRMATION}" ]]; then
  echo "Refusing reset. Use --apply --confirm ${CONFIRMATION}." >&2
  exit 2
fi

if [[ -n "${SUPABASE_DB_URL:-}" || -n "${DATABASE_URL:-}" ]]; then
  echo "Refusing reset while SUPABASE_DB_URL or DATABASE_URL is set." >&2
  exit 2
fi

command -v supabase >/dev/null 2>&1 || {
  echo "Supabase CLI is required." >&2
  exit 127
}

supabase --workdir "${INFRA_DIR}" db reset --local
