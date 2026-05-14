# D8 Round 2 Metrics Spec

This is the second-beta data dashboard specification for D8-4. It defines the
seven-day first-batch metrics, copy/paste SQL templates, and a Grafana panel
sketch. It does not add Grafana JSON, schema, API, or CI changes.

Runbook alignment:

- First-day operations stay aligned with [docs/BETA_CHECKLIST.md](BETA_CHECKLIST.md).
- The one-command seven-day report is [scripts/beta/d8_4_report.sh](../scripts/beta/d8_4_report.sh).
- The operational D8-4 package is [docs/D8_4_BETA_DASHBOARD.md](D8_4_BETA_DASHBOARD.md).

## Operating Window

Use a seven-day rolling window for the first second-beta batch:

```bash
cd /opt/eris
DAYS=7 bash scripts/beta/d8_4_report.sh
```

For manual SQL, start every SSH session with:

```bash
cd /opt/eris
POSTGRES_USER=$(awk -F= '/^POSTGRES_USER=/{print $2}' .env 2>/dev/null | tail -n1)
POSTGRES_DB=$(awk -F= '/^POSTGRES_DB=/{print $2}' .env 2>/dev/null | tail -n1)
POSTGRES_USER=${POSTGRES_USER:-eris}
POSTGRES_DB=${POSTGRES_DB:-eris}
```

Then run SQL with:

```bash
docker exec eris-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v days=7 -c "<SQL>"
```

No command in this document includes database passwords or third-party keys.

## Metric Inventory

| Group | Metric | Purpose | Healthy read | BETA_CHECKLIST alignment |
| --- | --- | --- | --- | --- |
| Health | `/health/detail` all-ok | Stop invites if API/DB/Redis is unhealthy | `api`, `db`, and `redis` are all `ok` | Preflight and pause rules |
| Cohort | users created / onboarded | Verify every invited user reaches consent | invited users eventually have `gdpr_consent_at` | First-day onboarding completion |
| Reply continuity | users with user messages and assistant replies | Catch bot silence quickly | assistant replies track user messages | First-day reply continuity |
| D1 retention | eligible users returning on day 1 | Core D8-4 beta outcome | read only after `d1_eligible_users > 0` | Extends first-day metrics to seven days |
| Score distribution | loneliness/dependency/initiation/emotion/retention/risk percentiles | See whether score fields are moving or stuck | non-null `n`, believable spread | Supports score distribution roadmap wording |
| Token/cost floor | persisted-message token estimate by day/model | Lower-bound cost watch without secrets | known model names, trend not spiking | Extends Stripe/cost watch |
| Handoff | status counts and stale locks | Avoid operator backlog | stale locks should be zero | Handoff health |
| Orders | order status and paid count | Watch Stripe test flow | pending is OK unless payment was expected | Stripe health |
| Notifications | notification task status | Catch noisy or stuck proactive jobs | failed/stuck counts stay low | Operational guardrail |
| Data quality | missing profiles, empty conversations, model names missing | Decide whether dashboard data is trustworthy | counts trend toward zero | Issue triage before inviting more users |

## SQL Templates

All SQL below is read-only `SELECT`.

### 1. Cohort Summary

```bash
docker exec eris-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v days=7 -c "
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
LEFT JOIN user_activity a ON a.user_id = u.id;"
```

### 2. D1 Retention By Cohort Day

```bash
docker exec eris-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v days=7 -c "
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
ORDER BY cohort_day;"
```

### 3. Score Distribution

```bash
docker exec eris-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v days=7 -c "
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
ORDER BY metric;"
```

### 4. Token And Cost Floor By Day

The application does not yet persist provider usage. This is a lower bound from
persisted message text only. Set price assumptions in shell variables, not in
the document:

```bash
PROMPT_USD_PER_1K=0.00015
COMPLETION_USD_PER_1K=0.00060
```

```bash
docker exec eris-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -v days=7 \
  -v prompt_usd_per_1k="$PROMPT_USD_PER_1K" \
  -v completion_usd_per_1k="$COMPLETION_USD_PER_1K" \
  -c "
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
ORDER BY day, model_name;"
```

### 5. Operational Guardrails

```bash
docker exec eris-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
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
ORDER BY metric, status;"
```

### 6. Data Quality Checks

```bash
docker exec eris-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v days=7 -c "
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
  AND (model_name IS NULL OR model_name = '');"
```

## Grafana Panel Sketch

Future Grafana JSON should be small and operational. One dashboard is enough:

```text
+--------------------------------------------------------------------------------+
| D8-4 Round 2 Beta                                                              |
| Window: 7d | Last refresh: $__timeTo() | Health: api/db/redis                  |
+----------------------+----------------------+----------------------+-----------+
| Users created        | Onboarding done      | D1 eligible          | D1 retained |
| stat                 | stat                 | stat                 | stat/%      |
+----------------------+----------------------+----------------------+-----------+
| D1 retention by cohort day                                                     |
| time series or bar: cohort_day -> d1_retention_pct, d1_eligible_users          |
+--------------------------------------------------------------------------------+
| Reply continuity                                                               |
| time series: user messages vs assistant/ai messages by day                     |
+--------------------------------------------------------------------------------+
| Score distribution                                                             |
| table/heatmap: metric, n, p25, p50, p75, p90, avg                              |
+--------------------------------------------------------------------------------+
| Token and cost floor                                                           |
| stacked bar: persisted_message_tokens by model/day; stat: cost floor USD       |
+--------------------------------------------------------------------------------+
| Guardrails                                                                     |
| handoff status | order status | notification status | data-quality failures    |
+--------------------------------------------------------------------------------+
```

Panel notes:

- Put health and invite safety at the top. Operators should not scroll to see a
  stop condition.
- D1 retention should show both percentage and denominator. A 100% value with
  `d1_eligible_users=1` is not a trend.
- Score distribution should remain a table until D4-3/D4-4 scoring is fully
  implemented and trusted.
- Token cost must be labeled "floor estimate" until provider usage is persisted.

## Pause Conditions

Pause the second-beta invite wave if any of these are true:

- `/health/detail` is not all `ok`.
- Two invited users fail onboarding.
- User messages increase but assistant messages do not for more than 10 minutes.
- Any `HUMAN_LOCKED` handoff remains locked longer than 15 minutes.
- The D8-4 report cannot run.
- Data-quality checks show missing profiles for newly created beta users.
- Any privacy or unauthenticated-data exposure is reported.

## Seven-Day Review Template

Use this after the first batch reaches seven days:

```text
D8-4 Round 2 Beta Review
window:
invited_users:
onboarding_completed:
d1_eligible_users:
d1_returned_users:
d1_retention_pct:
score_distribution_notes:
token_cost_floor_usd:
handoff_incidents:
stripe_order_notes:
data_quality_issues:
decision: continue / pause / rollback / expand beta
follow_up_tasks:
```
