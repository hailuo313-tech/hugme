# D6-4 Notification Queue Design

Status: queue contract and safe API skeleton implemented.

## Goal

Use `notification_tasks` as the single source of truth for proactive Telegram notifications. D6-3 decides eligibility and strategy; D6-4 queues, rate-limits, exposes admin visibility, and defines how the future worker sends.

No automatic sender worker is enabled yet.

## State Machine

```text
pending -> sending -> sent
pending -> cancelled
pending -> sending -> failed -> pending
pending -> sending -> failed
```

Status meanings:

- `pending`: accepted, waiting for worker.
- `sending`: worker has claimed it.
- `sent`: provider accepted the message.
- `failed`: provider or validation failed.
- `cancelled`: operator/system cancelled before send.

## API Contract

Create a task:

```http
POST /api/v1/notifications/schedule
```

```json
{
  "user_id": "uuid",
  "channel": "telegram",
  "notification_type": "silent_reactivation",
  "scheduled_at": "2026-05-12T16:15:00",
  "payload": {
    "strategy": "silent_reactivation",
    "tier": "D1",
    "reason": "inactive_24h",
    "template_hint": "gentle_check_in"
  }
}
```

Response:

```json
{
  "notification_id": "uuid",
  "status": "pending",
  "scheduled_at": "2026-05-12T16:15:00",
  "payload": {
    "dedupe_key": "silent_reactivation:D1:<user_id>:2026-05-12"
  }
}
```

List tasks:

```http
GET /api/v1/notifications/tasks?status=pending&limit=50
```

Cancel pending task:

```http
POST /api/v1/notifications/tasks/{task_id}/cancel
```

## Eligibility Gates

Schedule rejects with `409` when:

- user is not active
- `notification_opt_in = false`
- `opt_out_marketing = true`
- user is suspected minor
- `risk_level in ('high', 'critical')`
- open handoff task exists

Unsupported channels reject with `422`. Current allowed channel:

```text
telegram
```

## Frequency Caps

For `silent_reactivation`:

```text
1 per user per 24h
3 per user per 7d
```

The API checks existing `pending`, `sending`, and `sent` tasks.

## Deduplication

`payload.dedupe_key` is required logically. If omitted, the API derives:

```text
<strategy>:<tier>:<user_id>:<scheduled_date>
```

Until the table has a first-class `dedupe_key` column, dedupe is enforced against `payload ->> 'dedupe_key'`.

Recommended migration later:

```sql
ALTER TABLE notification_tasks ADD COLUMN dedupe_key varchar;
CREATE UNIQUE INDEX notification_tasks_dedupe_active_idx
ON notification_tasks (dedupe_key)
WHERE status IN ('pending', 'sending', 'sent');
```

## Worker Claim Contract

Future worker should claim one row atomically:

```sql
UPDATE notification_tasks
SET status = 'sending'
WHERE id = (
  SELECT id
  FROM notification_tasks
  WHERE status = 'pending'
    AND scheduled_at <= NOW()
  ORDER BY scheduled_at ASC, created_at ASC
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
RETURNING *;
```

Send via Telegram:

```text
POST https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/sendMessage
```

`chat_id` comes from `users.external_id` after removing the `tg_` prefix.

## Admin Visibility

Admin should display:

- `id`
- `user_id`
- `external_id`
- `channel`
- `notification_type`
- `payload.tier`
- `payload.reason`
- `scheduled_at`
- `sent_at`
- `status`
- `failure_reason`
- `created_at`

Actions:

- cancel pending task
- filter by status/user
- retry failed task, once D6 worker exists

## Rollback

Pause creation:

```text
Disable callers that create notification_tasks.
```

Cancel pending silent reactivation:

```sql
UPDATE notification_tasks
SET status = 'cancelled',
    failure_reason = 'D6-4 rollback'
WHERE notification_type = 'silent_reactivation'
  AND status = 'pending';
```

Do not delete sent rows.
