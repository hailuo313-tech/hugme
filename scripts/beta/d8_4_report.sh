#!/usr/bin/env bash
set -euo pipefail

DAYS="${DAYS:-7}"
DB_CONTAINER="${DB_CONTAINER:-eris-postgres}"
DB_USER="${DB_USER:-eris}"
DB_NAME="${DB_NAME:-eris}"
PROMPT_USD_PER_1K="${PROMPT_USD_PER_1K:-0}"
COMPLETION_USD_PER_1K="${COMPLETION_USD_PER_1K:-0}"
REPORT_FILE="${REPORT_FILE:-}"

if [[ -n "$REPORT_FILE" ]]; then
  mkdir -p "$(dirname "$REPORT_FILE")"
  exec > >(tee "$REPORT_FILE")
fi

psql_exec() {
  local sql
  sql="$(cat)"
  if [[ -n "${PSQL_DSN:-}" ]]; then
    printf '%s\n' "$sql" | psql "$PSQL_DSN" \
      -v ON_ERROR_STOP=1 \
      -v days="$DAYS" \
      -v prompt_usd_per_1k="$PROMPT_USD_PER_1K" \
      -v completion_usd_per_1k="$COMPLETION_USD_PER_1K"
  else
    printf '%s\n' "$sql" | docker exec -i "$DB_CONTAINER" psql \
      -U "$DB_USER" \
      -d "$DB_NAME" \
      -v ON_ERROR_STOP=1 \
      -v days="$DAYS" \
      -v prompt_usd_per_1k="$PROMPT_USD_PER_1K" \
      -v completion_usd_per_1k="$COMPLETION_USD_PER_1K"
  fi
}

section() {
  printf '\n== %s ==\n' "$1"
}

echo "ERIS D8-4 beta dashboard report"
echo "generated_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "window_days=$DAYS"
echo "pricing_prompt_usd_per_1k=$PROMPT_USD_PER_1K"
echo "pricing_completion_usd_per_1k=$COMPLETION_USD_PER_1K"
echo "note=token cost is a persisted-message floor estimate; prompt/system/history overhead is not stored yet"

section "1. Beta cohort summary"
psql_exec <<'SQL'
WITH beta_users AS (
  SELECT *
  FROM users
  WHERE created_at >= NOW() - ((:days)::int * INTERVAL '1 day')
),
user_activity AS (
  SELECT
    u.id AS user_id,
    EXISTS (
      SELECT 1
      FROM conversations c
      JOIN messages m ON m.conversation_id = c.id
      WHERE c.user_id = u.id
        AND m.sender_type = 'user'
    ) AS sent_any_message,
    EXISTS (
      SELECT 1
      FROM conversations c
      JOIN messages m ON m.conversation_id = c.id
      WHERE c.user_id = u.id
        AND m.sender_type IN ('assistant', 'ai')
    ) AS got_assistant_reply,
    EXISTS (
      SELECT 1
      FROM conversations c
      JOIN messages m ON m.conversation_id = c.id
      WHERE c.user_id = u.id
        AND m.sender_type = 'user'
        AND m.created_at >= u.created_at + INTERVAL '1 day'
        AND m.created_at <  u.created_at + INTERVAL '2 days'
    ) AS returned_d1
  FROM beta_users u
)
SELECT
  COUNT(*) AS users_created,
  COUNT(*) FILTER (WHERE u.gdpr_consent_at IS NOT NULL) AS onboarding_completed,
  COUNT(*) FILTER (WHERE a.sent_any_message) AS users_with_messages,
  COUNT(*) FILTER (WHERE a.got_assistant_reply) AS users_with_assistant_reply,
  COUNT(*) FILTER (WHERE u.created_at <= NOW() - INTERVAL '1 day') AS d1_eligible_users,
  COUNT(*) FILTER (
    WHERE u.created_at <= NOW() - INTERVAL '1 day'
      AND a.returned_d1
  ) AS d1_returned_users,
  ROUND(
    100.0 * COUNT(*) FILTER (
      WHERE u.created_at <= NOW() - INTERVAL '1 day'
        AND a.returned_d1
    ) / NULLIF(COUNT(*) FILTER (WHERE u.created_at <= NOW() - INTERVAL '1 day'), 0),
    1
  ) AS d1_retention_pct
FROM beta_users u
LEFT JOIN user_activity a ON a.user_id = u.id;
SQL

section "2. D1 retention by cohort day"
psql_exec <<'SQL'
WITH beta_users AS (
  SELECT *
  FROM users
  WHERE created_at >= NOW() - ((:days)::int * INTERVAL '1 day')
),
activity AS (
  SELECT
    u.id AS user_id,
    date_trunc('day', u.created_at)::date AS cohort_day,
    u.gdpr_consent_at IS NOT NULL AS onboarded,
    u.created_at <= NOW() - INTERVAL '1 day' AS d1_eligible,
    EXISTS (
      SELECT 1
      FROM conversations c
      JOIN messages m ON m.conversation_id = c.id
      WHERE c.user_id = u.id
        AND m.sender_type = 'user'
        AND m.created_at >= u.created_at + INTERVAL '1 day'
        AND m.created_at <  u.created_at + INTERVAL '2 days'
    ) AS returned_d1
  FROM beta_users u
)
SELECT
  cohort_day,
  COUNT(*) AS users_created,
  COUNT(*) FILTER (WHERE onboarded) AS onboarding_completed,
  COUNT(*) FILTER (WHERE d1_eligible) AS d1_eligible_users,
  COUNT(*) FILTER (WHERE d1_eligible AND returned_d1) AS d1_returned_users,
  ROUND(
    100.0 * COUNT(*) FILTER (WHERE d1_eligible AND returned_d1)
    / NULLIF(COUNT(*) FILTER (WHERE d1_eligible), 0),
    1
  ) AS d1_retention_pct
FROM activity
GROUP BY cohort_day
ORDER BY cohort_day;
SQL

section "3. Score distribution"
psql_exec <<'SQL'
WITH beta_profiles AS (
  SELECT p.*
  FROM user_profiles p
  JOIN users u ON u.id = p.user_id
  WHERE u.created_at >= NOW() - ((:days)::int * INTERVAL '1 day')
),
scores AS (
  SELECT 'loneliness_score' AS metric, loneliness_score::float AS value FROM beta_profiles
  UNION ALL SELECT 'dependency_score', dependency_score::float FROM beta_profiles
  UNION ALL SELECT 'initiation_score', initiation_score::float FROM beta_profiles
  UNION ALL SELECT 'emotion_score', emotion_score::float FROM beta_profiles
  UNION ALL SELECT 'retention_score', retention_score::float FROM beta_profiles
  UNION ALL SELECT 'risk_score', risk_score::float FROM beta_profiles
)
SELECT
  metric,
  COUNT(value) AS n,
  ROUND(MIN(value)::numeric, 2) AS min,
  ROUND(percentile_disc(0.25) WITHIN GROUP (ORDER BY value)::numeric, 2) AS p25,
  ROUND(percentile_disc(0.50) WITHIN GROUP (ORDER BY value)::numeric, 2) AS p50,
  ROUND(percentile_disc(0.75) WITHIN GROUP (ORDER BY value)::numeric, 2) AS p75,
  ROUND(percentile_disc(0.90) WITHIN GROUP (ORDER BY value)::numeric, 2) AS p90,
  ROUND(MAX(value)::numeric, 2) AS max,
  ROUND(AVG(value)::numeric, 2) AS avg
FROM scores
WHERE value IS NOT NULL
GROUP BY metric
ORDER BY metric;
SQL

section "4. Token and cost floor estimate by day"
psql_exec <<'SQL'
WITH recent_messages AS (
  SELECT
    date_trunc('day', m.created_at)::date AS day,
    COALESCE(NULLIF(m.model_name, ''), 'unknown') AS model_name,
    m.sender_type,
    CEIL(GREATEST(length(COALESCE(m.content, '')), 1) / 4.0)::bigint AS estimated_tokens
  FROM messages m
  WHERE m.created_at >= NOW() - ((:days)::int * INTERVAL '1 day')
),
daily AS (
  SELECT
    day,
    model_name,
    SUM(estimated_tokens) FILTER (WHERE sender_type = 'user') AS user_message_tokens,
    SUM(estimated_tokens) FILTER (WHERE sender_type IN ('assistant', 'ai')) AS assistant_message_tokens,
    SUM(estimated_tokens) AS persisted_message_tokens
  FROM recent_messages
  GROUP BY day, model_name
)
SELECT
  day,
  model_name,
  COALESCE(user_message_tokens, 0) AS user_message_tokens,
  COALESCE(assistant_message_tokens, 0) AS assistant_message_tokens,
  COALESCE(persisted_message_tokens, 0) AS persisted_message_tokens,
  ROUND((
    COALESCE(user_message_tokens, 0) * (:prompt_usd_per_1k)::numeric / 1000.0
    + COALESCE(assistant_message_tokens, 0) * (:completion_usd_per_1k)::numeric / 1000.0
  )::numeric, 6) AS estimated_cost_usd_floor
FROM daily
ORDER BY day, model_name;
SQL

section "5. Operational guardrails"
psql_exec <<'SQL'
SELECT 'handoff_tasks_24h_by_status' AS metric, status, COUNT(*) AS count
FROM handoff_tasks
WHERE created_at >= NOW() - INTERVAL '24 hours'
GROUP BY status
UNION ALL
SELECT 'orders_24h_by_status' AS metric, status, COUNT(*) AS count
FROM orders
WHERE created_at >= NOW() - INTERVAL '24 hours'
GROUP BY status
UNION ALL
SELECT 'notification_tasks_24h_by_status' AS metric, status, COUNT(*) AS count
FROM notification_tasks
WHERE created_at >= NOW() - INTERVAL '24 hours'
GROUP BY status
ORDER BY metric, status;
SQL

section "6. Data quality checks"
psql_exec <<'SQL'
SELECT
  'users_without_profile' AS check_name,
  COUNT(*) AS count
FROM users u
LEFT JOIN user_profiles p ON p.user_id = u.id
WHERE u.created_at >= NOW() - ((:days)::int * INTERVAL '1 day')
  AND p.user_id IS NULL
UNION ALL
SELECT
  'conversations_without_messages' AS check_name,
  COUNT(*) AS count
FROM (
  SELECT c.id
  FROM conversations c
  LEFT JOIN messages m ON m.conversation_id = c.id
  WHERE c.created_at >= NOW() - ((:days)::int * INTERVAL '1 day')
  GROUP BY c.id
  HAVING COUNT(m.id) = 0
) empty_conversations
UNION ALL
SELECT
  'assistant_messages_without_model_name' AS check_name,
  COUNT(*) AS count
FROM messages
WHERE created_at >= NOW() - ((:days)::int * INTERVAL '1 day')
  AND sender_type IN ('assistant', 'ai')
  AND (model_name IS NULL OR model_name = '');
SQL

echo
echo "Report complete."
