#!/usr/bin/env bash
# Seed CI/staging operator for E2E handoff APIs (idempotent).
set -euo pipefail
DB_CONTAINER="${DB_CONTAINER:-eris-postgres}"
DB_USER="${DB_USER:-eris}"
DB_NAME="${DB_NAME:-eris}"
E2E_OPERATOR_USER="${E2E_OPERATOR_USER:-e2e_ci}"
E2E_OPERATOR_PASSWORD="${E2E_OPERATOR_PASSWORD:-e2e_ci_secret}"

PYTHON_BIN="${PYTHON_BIN:-python3}"
HASH="$("$PYTHON_BIN" -c "import hashlib; print(hashlib.sha256('${E2E_OPERATOR_PASSWORD}'.encode()).hexdigest())")"

SQL="
INSERT INTO operators (username, password_hash, display_name, role, status)
VALUES ('${E2E_OPERATOR_USER}', '${HASH}', 'E2E CI Operator', 'operator', 'active')
ON CONFLICT (username) DO UPDATE SET
  password_hash = EXCLUDED.password_hash,
  status = 'active';
"

if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -qx "$DB_CONTAINER"; then
  docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "$SQL"
else
  echo "FAIL: docker container $DB_CONTAINER not running" >&2
  exit 1
fi

echo "Seeded operator: $E2E_OPERATOR_USER"
