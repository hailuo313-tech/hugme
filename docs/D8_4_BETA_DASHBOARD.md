# D8-4 Beta Dashboard

This is the read-only operating package for the second beta round. It prepares
the seven-day first-batch data view without adding schema, public API, or CI
changes.

## Readiness

D8-4 data preparation can run now. Do not start the second invite wave until:

- The production deploy guard from PR #20 is merged and used on the server.
- The unauthenticated memories endpoint is hardened.
- Stale open PRs are closed or rebased onto current `main`.
- `/health/detail` returns `api`, `db`, and `redis` as `ok`.
- A backup newer than 24 hours exists in `/opt/eris/backups/`.

## Run The Report

On the production server:

```bash
cd /opt/eris
DAYS=7 bash scripts/beta/d8_4_report.sh
```

Save a copy for the beta log:

```bash
cd /opt/eris
REPORT_FILE=/opt/eris/backups/d8_4_report_$(date -u +%Y%m%dT%H%M%SZ).txt \
  DAYS=7 \
  bash scripts/beta/d8_4_report.sh
```

If you are running against a direct Postgres DSN instead of Docker:

```bash
PSQL_DSN='postgresql://eris:eris_secret_2026@127.0.0.1:5432/eris' \
  DAYS=7 \
  bash scripts/beta/d8_4_report.sh
```

## Token Cost Inputs

The app does not yet persist provider `usage.prompt_tokens` or
`usage.completion_tokens`. The D8-4 report therefore prints a floor estimate
from persisted message text only:

- user message tokens: `ceil(length(content) / 4)`
- assistant message tokens: `ceil(length(content) / 4)`
- excludes system prompt, memory context, recent history, retries, embedding
  calls, failed LLM calls, and provider-side billing rounding

Set explicit price assumptions if you want a cost column:

```bash
PROMPT_USD_PER_1K=0.00015 \
COMPLETION_USD_PER_1K=0.00060 \
DAYS=7 \
bash scripts/beta/d8_4_report.sh
```

Keep the pricing values in the beta note so future readers know what was
assumed. If these values are left at `0`, the cost column intentionally reads
as zero while token volume still appears.

## Metric Definitions

### D1 Retention

Cohort: users whose `users.created_at` is inside the report window.

A user is D1 eligible once `users.created_at <= now() - interval '1 day'`.

A user is D1 retained when they have at least one `messages.sender_type='user'`
message in the window:

```text
[users.created_at + 1 day, users.created_at + 2 days)
```

This is strict calendar-relative D1 behavior, not rolling 24-hour activity.

### Score Distribution

The score table reads `user_profiles` for users created inside the report
window and summarizes:

- `loneliness_score`
- `dependency_score`
- `initiation_score`
- `emotion_score`
- `retention_score`
- `risk_score`

Each row prints `n`, `min`, `p25`, `p50`, `p75`, `p90`, `max`, and `avg`.

### Token Cost

The token section groups persisted-message token estimates by day and
`messages.model_name`.

For D8-4, treat it as a lower bound. A future hardening task should persist
LLM usage in a dedicated table or on `messages.safety_result`/metadata so that
actual provider cost can replace the estimate.

### Operational Guardrails

The report also prints 24-hour counts for:

- `handoff_tasks.status`
- `orders.status`
- `notification_tasks.status`

These are not the headline D8-4 metrics, but they help decide whether to pause
new invites.

## How To Read Results

Healthy second-beta behavior:

- `onboarding_completed` should match invited users after they finish `/start`.
- `users_with_assistant_reply` should track users with messages.
- `d1_retention_pct` should be interpreted only after enough users are
  `d1_eligible`.
- `assistant_messages_without_model_name` should trend toward zero. Nonzero
  means cost by model is not trustworthy.
- Any pending handoff older than the operating window should be inspected
  before inviting more users.

Pause the second beta if:

- `/health/detail` is not all `ok`.
- Two invited users fail onboarding.
- Assistant replies fail for more than 10 minutes.
- Any endpoint exposes private user data without operator auth.
- The D8-4 report cannot be generated.

## Daily Cadence

Run the report at:

- before invite wave
- +1 hour after first invite
- +4 hours
- +24 hours
- daily until the first batch reaches seven days

Attach the saved report path to the beta notes or incident note.
