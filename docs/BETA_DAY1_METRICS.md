# Beta Day-1 Metrics

This is the copy/paste metric pack for the first beta day. It aligns with
`docs/BETA_CHECKLIST.md` section 3 and only runs read-only `SELECT` queries.

Run from the production checkout after SSH:

```bash
cd /opt/eris
```

The commands below do not hard-code a database password. They run `psql` inside
the `eris-postgres` container as `POSTGRES_USER` / `POSTGRES_DB` from `.env`
when available, falling back to `eris`.

## One-Command Report

```bash
cd /opt/eris
WINDOW_HOURS=24 bash scripts/beta/day1_metrics.sh
```

Useful overrides:

```bash
DB_CONTAINER=eris-postgres DB_USER=eris DB_NAME=eris WINDOW_HOURS=24 \
  bash scripts/beta/day1_metrics.sh
```

If you prefer a direct DSN, set `PSQL_DSN` in your shell rather than writing it
into the command history:

```bash
PSQL_DSN="$ERIS_PSQL_DSN" WINDOW_HOURS=24 bash scripts/beta/day1_metrics.sh
```

## Metric 0: Health

Purpose: system health must remain all `ok`.

```bash
curl -fsS http://127.0.0.1:8000/health/detail
```

Expected:

```json
{"api":"ok","db":"ok","redis":"ok"}
```

## Metric 1: Onboarding Completion

Purpose: every invited beta user should eventually reach `gdpr_consent_at`.

```bash
POSTGRES_USER=$(awk -F= '/^POSTGRES_USER=/{print $2}' .env 2>/dev/null | tail -n1); POSTGRES_USER=${POSTGRES_USER:-eris}
POSTGRES_DB=$(awk -F= '/^POSTGRES_DB=/{print $2}' .env 2>/dev/null | tail -n1); POSTGRES_DB=${POSTGRES_DB:-eris}
docker exec eris-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
SELECT
  COUNT(*) AS users_total,
  COUNT(*) FILTER (WHERE gdpr_consent_at IS NOT NULL) AS onboarding_completed,
  COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') AS users_created_24h,
  COUNT(*) FILTER (
    WHERE gdpr_consent_at IS NOT NULL
      AND gdpr_consent_at > NOW() - INTERVAL '24 hours'
  ) AS onboarding_completed_24h
FROM users;"
```

Read with `BETA_CHECKLIST.md`:

- `users_total` maps to first-day user count.
- `onboarding_completed` maps to beta users that finished onboarding.
- `onboarding_completed_24h` helps spot users stuck during today’s invite wave.

## Metric 2: Reply Continuity

Purpose: assistant messages should grow after user messages.

```bash
POSTGRES_USER=$(awk -F= '/^POSTGRES_USER=/{print $2}' .env 2>/dev/null | tail -n1); POSTGRES_USER=${POSTGRES_USER:-eris}
POSTGRES_DB=$(awk -F= '/^POSTGRES_DB=/{print $2}' .env 2>/dev/null | tail -n1); POSTGRES_DB=${POSTGRES_DB:-eris}
docker exec eris-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
SELECT
  sender_type,
  COUNT(*) AS messages_24h,
  MIN(created_at) AS first_seen_at,
  MAX(created_at) AS last_seen_at
FROM messages
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY sender_type
ORDER BY sender_type;"
```

Read with `BETA_CHECKLIST.md`:

- `sender_type='user'` means beta users are sending messages.
- `sender_type='assistant'` or `sender_type='ai'` should be present after user
  messages. If user messages rise while assistant messages do not, pause invites.

## Metric 3: Conversation State

Purpose: conversation state should not accumulate in an unexpected state.

```bash
POSTGRES_USER=$(awk -F= '/^POSTGRES_USER=/{print $2}' .env 2>/dev/null | tail -n1); POSTGRES_USER=${POSTGRES_USER:-eris}
POSTGRES_DB=$(awk -F= '/^POSTGRES_DB=/{print $2}' .env 2>/dev/null | tail -n1); POSTGRES_DB=${POSTGRES_DB:-eris}
docker exec eris-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
SELECT
  state,
  COUNT(*) AS conversations_total,
  COUNT(*) FILTER (
    WHERE COALESCE(last_message_at, created_at) > NOW() - INTERVAL '24 hours'
  ) AS conversations_active_24h
FROM conversations
GROUP BY state
ORDER BY state;"
```

Read with `BETA_CHECKLIST.md`:

- Most normal beta conversations should stay `AI_ACTIVE`.
- `WAITING_OPERATOR` and `HUMAN_LOCKED` should be reviewed during beta.

## Metric 4: Handoff Health

Purpose: no handoff should remain locked for more than 15 minutes.

```bash
POSTGRES_USER=$(awk -F= '/^POSTGRES_USER=/{print $2}' .env 2>/dev/null | tail -n1); POSTGRES_USER=${POSTGRES_USER:-eris}
POSTGRES_DB=$(awk -F= '/^POSTGRES_DB=/{print $2}' .env 2>/dev/null | tail -n1); POSTGRES_DB=${POSTGRES_DB:-eris}
docker exec eris-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
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
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY status
ORDER BY status;"
```

Read with `BETA_CHECKLIST.md`:

- `stale_locked_over_15m` should be `0`.
- Any nonzero `WAITING_OPERATOR` or stale `HUMAN_LOCKED` count needs an operator
  check before inviting more users.

## Metric 5: Stripe Order Health

Purpose: order creation should be visible; test payments may remain `pending`
unless someone intentionally completes a test payment.

```bash
POSTGRES_USER=$(awk -F= '/^POSTGRES_USER=/{print $2}' .env 2>/dev/null | tail -n1); POSTGRES_USER=${POSTGRES_USER:-eris}
POSTGRES_DB=$(awk -F= '/^POSTGRES_DB=/{print $2}' .env 2>/dev/null | tail -n1); POSTGRES_DB=${POSTGRES_DB:-eris}
docker exec eris-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
SELECT
  status,
  COUNT(*) AS orders_24h,
  COUNT(*) FILTER (WHERE paid_at IS NOT NULL) AS paid_count,
  MIN(created_at) AS oldest_created_at,
  MAX(created_at) AS newest_created_at
FROM orders
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY status
ORDER BY status;"
```

Read with `BETA_CHECKLIST.md`:

- `pending` is acceptable for uncompleted test Checkout sessions.
- `paid_count` should rise only when a test payment is intentionally completed.

## Suggested Cadence

Run after each invite, then at `+1h`, `+4h`, and `+24h`.

Pause invites if:

- `/health/detail` is not all `ok`.
- Two users fail onboarding.
- User messages rise but assistant messages do not for more than 10 minutes.
- `stale_locked_over_15m` is nonzero.
- Any data-loss or privacy symptom appears.
