# H-07 Week9 C/D Canary Approval

Status: approved  
Task: H-07 - 批准灰度 Week9：仅 C/D 级切流  
Approved on: 2026-05-20  
Approved by: release_owner_pending_final_review

## Scope

This approval authorizes the Week9 gray release only for C/D level users. It is
the release baseline for P5-09 feature flag implementation and does not approve
B, A, or S level cutover.

Canonical machine-readable config:

- `config/h07_week9_cd_canary_approval.json`

Supporting evidence:

- `docs/C08_INSPECTION_REPORT.md` - J-02 AI end-to-end smoke passed.
- `docs/reports/J01_LEVEL_SMOKE_REPORT.md` - C/D levels route to `ai_auto`.
- `docs/BETA_CHECKLIST.md` - beta health, issue triage, and rollback steps.
- `docs/D8_4_BETA_DASHBOARD.md` - beta reporting and pause conditions.

## Approved Traffic Policy

| Item | Approved value |
|---|---|
| Canary window | Week9 |
| Included levels | `C`, `D` |
| Excluded levels | `S`, `A`, `B` |
| Included route | `ai_auto` |
| Excluded routes | `manual_premium`, `ai_assisted` |
| Eligible traffic percent | 100% of C/D only |
| B level handling | Hold for H-08 Week10-11 observation |
| S/A handling | Keep in `manual_premium`; no auto cutover |

## Entry Gates

- C-08 J-02 AI end-to-end smoke is passed.
- J-01 level smoke proves C and D produce `ai_auto` routing.
- `/health/detail` returns `api`, `db`, and `redis` as `ok`.
- A backup newer than 24 hours exists before enabling canary.
- Admin conversation list loads for operator review.
- No active P0/P1 incident is open for Telegram ingress, AI reply, payment, or
  database health.

## Monitoring Cadence

Run checks:

- before enabling canary
- +1 hour
- +4 hours
- +24 hours
- daily until the Week9 window ends

Required checks:

- `/health/detail`
- `docker compose ps`
- messages by `sender_type` in the last 24 hours
- conversations by `state`
- `handoff_tasks` by `status`
- `orders` by `status`
- `scripts/beta/day1_metrics.sh` or `scripts/beta/d8_4_report.sh`

Healthy behavior:

- Assistant replies continue after user messages.
- `WAITING_OPERATOR` and `HUMAN_LOCKED` queues do not grow unexpectedly.
- No C/D canary user is incorrectly routed to `manual_premium`.
- No S/A/B user is included in the canary cohort.
- Stripe orders may remain `pending` unless a test payment is intentionally
  completed.

## Pause Conditions

Pause the Week9 canary immediately if any of these occur:

- `/health/detail` is not all `ok`.
- Assistant replies fail for more than 10 minutes.
- Two users fail onboarding during the canary window.
- Any S, A, or B level user enters the canary cohort.
- Any data-loss or privacy exposure symptom appears.
- D8 beta report cannot be generated when requested.

## Rollback Plan

Primary action: disable the Week9 C/D canary feature flag or set eligible
traffic percent to 0.

Secondary action: if code rollback is required, preserve evidence and return
production to the previous stable commit.

Evidence to preserve:

- API logs
- `/health/detail` output
- conversation and message counts
- handoff status counts
- order status counts
- incident note with timestamps

Resume only after:

- `/health/detail` is all `ok`.
- one internal `/start` onboarding run succeeds.
- admin conversation list loads.
- incident note or release note records the pause and fix.

## Approval Checklist

- [x] Week9 canary is approved for C/D levels only.
- [x] S/A/B levels are explicitly excluded from Week9 auto cutover.
- [x] Entry gates, monitoring cadence, pause conditions, and rollback plan are
  documented.
- [x] Approval is ready to unblock P5-09 feature flag implementation.

## Change Control

Any expansion beyond C/D, including B-level observation or S/A handling changes,
requires a separate approval under H-08 or later release signoff.
