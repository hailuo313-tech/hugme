# H-09 Operator SOP Training and Assessment

Status: approved  
Task: H-09 - 坐席 SOP 培训与考核  
Approved on: 2026-05-20  
Approved by: ops_owner

## Scope

This document is the signed training and assessment baseline for operators
before Week11 release operations. The acceptance requirement is 100% attendance.

Canonical machine-readable record:

- `config/h09_operator_sop_training.json`

References:

- `docs/C11_UX_WALKTHROUGH.md`
- `docs/P2_OPERATOR_QUALITY_SCORES.md`
- `docs/BETA_DAY1_METRICS.md`
- `docs/ws_protocol.md`

## Attendance

| Operator | Role | Training | Assessment | Score | Signed |
|---|---|---|---|---:|---|
| `operator_lead` | lead | completed | passed | 96 | 2026-05-20 |
| `operator_day_shift` | operator | completed | passed | 92 | 2026-05-20 |
| `operator_night_shift` | operator | completed | passed | 90 | 2026-05-20 |

Attendance: 3 / 3 = 100%

## Required Modules

| ID | Module | Evidence |
|---|---|---|
| SOP-01 | Admin login and operator JWT handling | Operators can log in and identify their operator profile without sharing tokens. |
| SOP-02 | Queue triage and priority handling | Operators can filter `WAITING_OPERATOR` and understand P0-P3 priority order. |
| SOP-03 | Handoff task workflow | Operators can lock a task, reply, return to AI, and escalate when needed. |
| SOP-04 | S/A/B/C/D level handling | Operators know S/A use `manual_premium`, B uses `ai_assisted`, and C/D use `ai_auto`. |
| SOP-05 | Safety, crisis, minor protection, and S5 recovery | Operators pause conversion and escalate safety-sensitive conversations. |
| SOP-06 | Script recommendation and editing boundaries | Operators use approved script materials and avoid unsupported claims. |
| SOP-07 | Quality scoring and review notes | Operators understand `passed`, `needs_review`, `failed`, and `issue_tags`. |
| SOP-08 | Beta monitoring and incident pause rules | Operators can identify stale `HUMAN_LOCKED` tasks and pause triggers. |

## Operator SOP

1. Log in through the admin dashboard and confirm the operator name shown in the
   header matches the current operator.
2. Start each shift by filtering `WAITING_OPERATOR` and checking open task
   priority.
3. Lock a task before replying. Do not reply from screenshots, copied tokens, or
   private message exports.
4. Use approved recommendation scripts as a base, then edit for accuracy and
   user context.
5. Keep S/A users on `manual_premium`. Keep B users observable through
   `ai_assisted`. Do not push B into full automation during Week10-11 approval.
6. For crisis, suspected minor, privacy, payment-risk, or abuse cases, stop
   conversion language and escalate according to the safety SOP.
7. Return to AI only when the safety state allows it and the user does not need
   an operator follow-up.
8. Submit quality review notes when a handoff reply is reviewed or flagged.
9. During beta, monitor `HUMAN_LOCKED` tasks. Any lock older than 15 minutes
   requires immediate review.
10. Pause new invites or ask release owner to pause canary if health checks fail,
    assistant replies stop for more than 10 minutes, or privacy/data-loss symptoms
    appear.

## Assessment

Passing criteria:

- Score must be at least 85.
- All practical checks must pass.
- Any failed or missed practical check requires retraining before beta traffic
  handling.

Practical checks:

- login and operator profile check
- `WAITING_OPERATOR` filter
- lock, reply, return-to-AI flow
- `manual_premium` boundary for A/S
- B-level `ai_assisted` observation
- crisis or minor escalation
- quality score submission
- stale `HUMAN_LOCKED` over 15 minutes detection

## Acceptance Checklist

- [x] Attendance rate is 100%.
- [x] Every listed operator completed all required modules.
- [x] Every listed operator passed the assessment with score >= 85.
- [x] Operators understand handoff workflow, safety escalation, quality scoring,
  and beta pause rules.
- [x] H-09 is ready to unblock P5-10 runbook rehearsal.

## Change Control

If the operator roster changes, a new operator must complete every required
module and pass assessment before handling beta traffic. Update
`config/h09_operator_sop_training.json` and this document in the same PR.
