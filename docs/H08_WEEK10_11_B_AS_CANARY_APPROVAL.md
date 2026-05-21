# H-08 Week10-11 B Observation and A/S Handoff Approval

Status: approved  
Task: H-08 - 批准灰度 Week10-11：B 级观察 + A/S 接管  
Approved on: 2026-05-20  
Approved by: release_owner

## Scope

This approval expands the gray release after H-07. Week10-11 keeps C/D on the
automatic path, allows B-level users into observation through `ai_assisted`, and
requires A/S users to stay on `manual_premium` handoff.

Canonical machine-readable config:

- `config/h08_week10_11_bas_approval.json`

Supporting evidence:

- `docs/LEVEL_ENGINE_REVIEW_C05.md` - route contract: S/A -> `manual_premium`,
  B -> `ai_assisted`, C/D -> `ai_auto`.
- `docs/reports/J01_LEVEL_SMOKE_REPORT.md` - J-01 level smoke passed.
- `docs/BETA_CHECKLIST.md` - beta health, issue triage, and rollback steps.
- `docs/D8_4_BETA_DASHBOARD.md` - beta reporting and pause conditions.

## Dependency

H-08 may be enabled only after H-07 is accepted and the Week9 C/D-only canary has
no unresolved P0/P1 incident.

## Approved Traffic Policy

| Level | Week10-11 policy | Route | Boundary |
|---|---|---|---|
| `S` | Operator handoff | `manual_premium` | Must not enter `ai_auto`. |
| `A` | Operator handoff | `manual_premium` | Must not enter `ai_auto`. |
| `B` | Observation | `ai_assisted` | Visible in admin; not approved for full `ai_auto`. |
| `C` | Continue H-07 auto canary | `ai_auto` | Continue only while H-07 health remains stable. |
| `D` | Continue H-07 auto canary | `ai_auto` | Continue only while H-07 health remains stable. |

## Entry Gates

- H-07 Week9 C/D-only approval is accepted.
- No unresolved P0/P1 incident remains from Week9 canary.
- J-01 level smoke proves S/A route to `manual_premium`, B routes to
  `ai_assisted`, and C/D route to `ai_auto`.
- `/health/detail` returns `api`, `db`, and `redis` as `ok`.
- Admin conversation list and operator handoff views load for review.
- A backup newer than 24 hours exists before enabling Week10-11 canary.

## Monitoring Cadence

Run checks:

- before enabling
- +1 hour
- +4 hours
- +24 hours
- daily until the window ends
- end of Week10
- end of Week11

Required checks:

- `/health/detail`
- `docker compose ps`
- level distribution by S/A/B/C/D
- route distribution by `manual_premium`, `ai_assisted`, `ai_auto`
- B-level conversations reviewed in admin
- A/S handoff queue age
- `handoff_tasks` by status
- messages by `sender_type` in the last 24 hours
- `orders` by status
- `scripts/beta/d8_4_report.sh`

Healthy behavior:

- C/D automatic flow remains stable after H-07.
- B users stay on `ai_assisted` and remain observable.
- A/S users route to `manual_premium` and are visible to operators.
- No A/S user is processed as `ai_auto`.
- No B user is processed as full `ai_auto`.
- Handoff queue age remains within the operator SLA.

## Pause Conditions

Pause Week10-11 expansion immediately if any of these occur:

- `/health/detail` is not all `ok`.
- Assistant replies fail for more than 10 minutes.
- Any A or S user is routed to `ai_auto`.
- Any B user is routed to `ai_auto` without explicit operator approval.
- A/S handoff queue age exceeds 15 minutes for any active user.
- Two users fail onboarding during the Week10-11 window.
- Any data-loss or privacy exposure symptom appears.
- D8 beta report cannot be generated when requested.

## Rollback Plan

Primary action: disable Week10-11 B observation and A/S handoff expansion, then
return to the H-07 C/D-only policy.

Secondary action: if H-07 behavior is also unstable, disable all canary traffic
by setting eligible traffic percent to 0.

Evidence to preserve:

- API logs
- `/health/detail` output
- level and route distribution
- handoff queue age snapshot
- conversation and message counts
- orders status counts
- incident note with timestamps

Resume only after:

- `/health/detail` is all `ok`.
- A/S handoff route is verified as `manual_premium`.
- B route is verified as `ai_assisted`.
- admin conversation list and handoff view load.
- incident note or release note records the pause and fix.

## Approval Checklist

- [x] Week10-11 expansion is approved only after H-07 is accepted.
- [x] B level is approved for observation via `ai_assisted`, not full `ai_auto`.
- [x] A/S levels are approved for `manual_premium` handoff only.
- [x] Pause and rollback criteria explicitly protect A/S and B routing
  boundaries.
- [x] Approval is ready to guide P5-09 feature flag behavior.

## Change Control

Any move from B observation to B auto handling, or any change to A/S handoff
policy, requires a later release approval and updated validation.
