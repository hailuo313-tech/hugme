#!/usr/bin/env bash
set -euo pipefail

DB_CONTAINER="${DB_CONTAINER:-eris-postgres}"
WINDOW_HOURS="${WINDOW_HOURS:-24}"

read_env_value() {
  local key="$1"
  local file="${2:-.env}"
  if [[ ! -f "$file" ]]; then
    return 1
  fi
  awk -F= -v key="$key" '
    $0 ~ "^[[:space:]]*" key "=" {
      value=$0
      sub("^[^=]*=", "", value)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      gsub(/^"|"$/, "", value)
      gsub(/^'\''|'\''$/, "", value)
      print value
      found=1
    }
    END { exit found ? 0 : 1 }
  ' "$file" | tail -n 1
}

DB_USER="${DB_USER:-$(read_env_value POSTGRES_USER || true)}"
DB_NAME="${DB_NAME:-$(read_env_value POSTGRES_DB || true)}"
DB_USER="${DB_USER:-eris}"
DB_NAME="${DB_NAME:-eris}"

psql_exec() {
  local title="$1"
  local sql="$2"
  printf '\n== %s ==\n' "$title"
  if [[ -n "${PSQL_DSN:-}" ]]; then
    psql "$PSQL_DSN" -v ON_ERROR_STOP=1 -v window_hours="$WINDOW_HOURS" -c "$sql"
  else
    docker exec "$DB_CONTAINER" psql \
      -U "$DB_USER" \
      -d "$DB_NAME" \
      -v ON_ERROR_STOP=1 \
      -v window_hours="$WINDOW_HOURS" \
      -c "$sql"
  fi
}

printf 'ERIS beta day-1 metrics\n'
printf 'run_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'working_dir=%s\n' "$(pwd)"
printf 'window_hours=%s\n' "$WINDOW_HOURS"
printf 'db_container=%s\n' "$DB_CONTAINER"
printf 'db_name=%s\n' "$DB_NAME"
printf 'db_user=%s\n' "$DB_USER"

printf '\n== 0. Health ==\n'
curl -fsS http://127.0.0.1:8000/health/detail
printf '\n'

psql_exec "1. Onboarding completion" "
SELECT
  COUNT(*) AS users_total,
  COUNT(*) FILTER (WHERE gdpr_consent_at IS NOT NULL) AS onboarding_completed,
  COUNT(*) FILTER (WHERE created_at > NOW() - (:'window_hours'::int * INTERVAL '1 hour')) AS users_created_in_window,
  COUNT(*) FILTER (
    WHERE gdpr_consent_at IS NOT NULL
      AND gdpr_consent_at > NOW() - (:'window_hours'::int * INTERVAL '1 hour')
  ) AS onboarding_completed_in_window
FROM users;
"

psql_exec "2. Reply continuity by sender_type" "
SELECT
  sender_type,
  COUNT(*) AS messages_24h,
  MIN(created_at) AS first_seen_at,
  MAX(created_at) AS last_seen_at
FROM messages
WHERE created_at > NOW() - (:'window_hours'::int * INTERVAL '1 hour')
GROUP BY sender_type
ORDER BY sender_type;
"

psql_exec "3. Conversation state distribution" "
SELECT
  state,
  COUNT(*) AS conversations_total,
  COUNT(*) FILTER (
    WHERE COALESCE(last_message_at, created_at) > NOW() - (:'window_hours'::int * INTERVAL '1 hour')
  ) AS conversations_active_in_window
FROM conversations
GROUP BY state
ORDER BY state;
"

psql_exec "4. Handoff health" "
SELECT
  status,
  COUNT(*) AS tasks_24h,
  COUNT(*) FILTER (
    WHERE status = 'HUMAN_LOCKED'
      AND locked_at < NOW() - INTERVAL '15 minutes'
  ) AS stale_locked_over_15m,
  MIN(created_at) AS oldest_created_at,
  MAX(created_at) AS newest_created_at
FROM handoff_tasks
WHERE created_at > NOW() - (:'window_hours'::int * INTERVAL '1 hour')
GROUP BY status
ORDER BY status;
"

psql_exec "5. Stripe order health" "
SELECT
  status,
  COUNT(*) AS orders_24h,
  COUNT(*) FILTER (WHERE paid_at IS NOT NULL) AS paid_count,
  MIN(created_at) AS oldest_created_at,
  MAX(created_at) AS newest_created_at
FROM orders
WHERE created_at > NOW() - (:'window_hours'::int * INTERVAL '1 hour')
GROUP BY status
ORDER BY status;
"

printf '\nDone. Compare these sections with docs/BETA_CHECKLIST.md §3.\n'
