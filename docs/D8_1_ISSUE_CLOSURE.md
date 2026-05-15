# D8-1 Issue Closure Ledger

This ledger answers whether the D7 -> D8 beta bug list is clear enough to
consider the roadmap item D8-1 narrowed or checkable. It records every D8-1
bugfix/preflight PR that was still open during the reconcile pass, and the
explicit close/merge/defer decision.

Snapshot:

- Checked at: 2026-05-14 PT / 2026-05-15 UTC.
- Source branch checked: `origin/main` at `7a26b90`.
- GitHub Issues: none open.
- D8-1 repair/preflight PRs left open before this pass: #30, #32, #33, #35.
- D8-1 repair/preflight PRs left open after this pass: none.

## Closure Table

| ID | Type | Title / scope | Final state | Decision | Evidence / reason | Follow-up |
| --- | --- | --- | --- | --- | --- | --- |
| #30 | PR | `fiX-01CDA3` / redis volume indentation | Closed 2026-05-15 UTC | Do not merge | PR had no file diff against `main` and no actionable D7 -> D8 bug description. | Reopen as a fresh scoped PR only if a reproducible compose volume issue remains. |
| #32 | PR | Admin routes, profile entry, loading states | Closed 2026-05-15 UTC | Do not merge stale branch | PR was `DIRTY` against `main`. Main already has `/admin/users/[id]` and admin profile/navigation work. Remaining loading-state or route polish is not a D8 beta blocker. | Split into a fresh D9/admin-UX follow-up if product still wants the polish. |
| #33 | PR | Admin auth guard, basePath redirect, half-auth hardening | Closed 2026-05-15 UTC | Do not merge stale branch | PR was `DIRTY` against `main`. Main already has `LOGIN_PATH=/admin/login`, 401 redirect through `LOGIN_PATH`, and half-auth clearing in the admin entry path. Remaining skeleton polish is not a D8 blocker. | Split into a fresh D9/admin-UX follow-up if operators still see blank-screen flashes. |
| #35 | PR | Admin beta preflight one-page checklist | Closed 2026-05-15 UTC | Superseded | Main already contains `docs/ADMIN_BETA_PREFLIGHT.md` and the `docs/BETA_CHECKLIST.md` preflight entry via PR #44. | None. |
| #38 | PR | Windows local dev setup | Open, non-blocking | Excluded from D8-1 bug list | Dev-environment documentation, not a D7 beta user bugfix/preflight blocker. | Track separately under D8 developer enablement. |
| #16 / #20 / #21 / #23 / #24 | PR | Older Devin feature/ops branches | Open, non-blocking | Excluded from D8-1 bug list | These are feature or policy branches, not D7 beta bugfix PRs. | Product owner can close/rebase separately; they do not block D8-1 issue clearance. |

## Current Answer

As of this snapshot, the D7 -> D8 issue list has no unresolved D8-1
bugfix/preflight PRs and no open GitHub Issues.

D8-1 may be treated as "issue list cleared" from a governance perspective.
Before changing the public roadmap to a green done state, still require one
release-owner confirmation that the current `main` build passes the intended
beta smoke path.

## Roadmap Guidance

- Safe wording: `D8-1 issue list cleared; beta smoke confirmation pending`.
- Do not claim fresh code was merged in this pass; the action here was triage
  and closure of stale/duplicate PRs.
- If any closed PR is reopened, add it back to this ledger with one of:
  `merge`, `close with reason`, or `defer to D9`.
