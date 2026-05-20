# D6-3 Silent Reactivation Strategy

Status: Codex review complete.

## Goal

Bring inactive users back without violating consent, quiet hours, emotional safety, or platform trust. This strategy feeds D6-4 `notification_tasks` and Telegram proactive push.

## Non-Negotiable Gates

A user is eligible only when all gates pass:

- `users.status = 'active'`
- `users.notification_opt_in = true`
- `users.opt_out_marketing = false`
- `users.is_minor_suspected = false`
- `users.channel = 'telegram'`
- Telegram bot token is configured
- No open high-risk human handoff task for the user
- Current local user time is outside quiet hours

If any gate fails, do not create a notification task. Log the skip reason in worker logs.

## Quiet Hours

Use `users.timezone`; default to `UTC` when missing or invalid.

Hard quiet window:

```text
21:30-09:00 local user time
```

Soft restriction:

```text
No more than 1 proactive message per user per 24h.
No more than 3 proactive messages per user per 7d.
```

If a task becomes due during quiet hours, move `scheduled_at` to the next local 09:15.

## Reactivation Tiers

### D1: Gentle Check-In

Trigger:

- Last user message was 24-36h ago.
- User has completed at least one conversation.
- No user message after the candidate task was scheduled.

Message intent:

- Gentle, low-pressure, no urgency.
- No sales language.
- Should sound like continuity from the last conversation.

Payload:

```json
{
  "tier": "D1",
  "tone": "gentle",
  "goal": "return_to_chat",
  "max_length": "short"
}
```

### D3: Memory-Based Reconnection

Trigger:

- Last user message was 72-96h ago.
- User has at least one meaningful memory or profile preference.
- No D1 response within 48h.

Message intent:

- Reference a stable, non-sensitive preference.
- Do not mention sensitive memories, crisis content, payments, loneliness score, or risk classification.

Payload:

```json
{
  "tier": "D3",
  "tone": "warm",
  "goal": "memory_reconnect",
  "memory_policy": "non_sensitive_only"
}
```

### D7: Last Light-Touch Ping

Trigger:

- Last user message was 7-9d ago.
- No response to D1/D3.
- User is not high-risk and has not opted out.

Message intent:

- One final low-pressure invitation.
- Explicitly easy to ignore.
- No guilt, fear, scarcity, or emotional dependence framing.

Payload:

```json
{
  "tier": "D7",
  "tone": "light",
  "goal": "final_ping",
  "cooldown_after_days": 14
}
```

## Safety Restrictions

Never send proactive messages when:

- User has recent crisis/self-harm content.
- `users.risk_level in ('high', 'critical')`.
- There is an open `handoff_tasks` row with `status in ('pending', 'PENDING', 'ESCALATED', 'HUMAN_LOCKED')`.
- Last operator message was within 24h.
- User explicitly asked not to be contacted.

For high-risk users, create or preserve a handoff task instead of marketing/reactivation.

## `notification_tasks` Contract

D6-3 should create tasks, not send directly.

Required fields:

```text
user_id
channel = 'telegram'
notification_type = 'silent_reactivation'
payload
scheduled_at
status = 'pending'
```

Payload shape:

```json
{
  "strategy": "silent_reactivation",
  "tier": "D1|D3|D7",
  "reason": "inactive_24h|inactive_72h|inactive_7d",
  "quiet_hours_checked": true,
  "timezone": "America/Tijuana",
  "template_hint": "gentle_check_in",
  "safety": {
    "risk_level": "normal",
    "notification_opt_in": true,
    "opt_out_marketing": false
  }
}
```

Recommended future fields for D6-4 migration:

```text
attempt_count integer default 0
last_attempt_at timestamp
dedupe_key varchar unique
cancelled_at timestamp
delivered_at timestamp
provider_message_id varchar
```

## Deduplication

Use a deterministic dedupe key:

```text
silent:<tier>:<user_id>:<YYYY-MM-DD local date>
```

Before inserting, check for an existing pending/sent task with the same dedupe key. Until the DB has a `dedupe_key` column, enforce this in the worker by querying `payload`.

## Rollback Plan

Immediate stop:

```text
Set SILENT_REACTIVATION_ENABLED=false
```

If the env flag is not implemented yet, stop by pausing the worker or disabling its scheduler.

Database rollback for unsent tasks:

```sql
UPDATE notification_tasks
SET status = 'cancelled',
    failure_reason = 'silent reactivation rollback'
WHERE notification_type = 'silent_reactivation'
  AND status = 'pending';
```

Provider rollback:

- Do not delete sent records.
- Add an incident note to the runbook.
- If a bad template was sent, freeze all D1/D3/D7 tasks for 24h.

## Observability

Worker logs must include:

```text
trace_id
user_id
tier
eligibility_result
skip_reason
scheduled_at
timezone
dedupe_key
```

Metrics for D7-1:

```text
silent_reactivation_candidates_total
silent_reactivation_skipped_total{reason}
silent_reactivation_tasks_created_total{tier}
silent_reactivation_sent_total{tier}
silent_reactivation_reply_total{tier}
```

## Acceptance Criteria

- Eligible D1/D3/D7 users produce pending `notification_tasks`.
- Opted-out users produce no task.
- Quiet-hour users are rescheduled to local 09:15.
- High-risk users are skipped and routed to handoff policy.
- Rollback SQL cancels all pending silent reactivation tasks.
