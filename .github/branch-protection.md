# Branch Protection Policy

This repository protects:

- `main`
- `release/*`

## Main Strategy

`main` is the only production deploy branch. Daily work must enter `main`
through pull requests; production deploys must run from `/opt/eris` on `main`
via `./deploy.sh`.

The active GitHub ruleset is:

- Name: `Protect main and release branches`
- Scope: `refs/heads/main`, `refs/heads/release/*`
- Enforcement: active

Rules:

- Require pull request before merge.
- Require 1 approving review.
- Dismiss stale approvals when new commits are pushed.
- Require conversation resolution.
- Require branches to be up to date before merge.
- Require selected status checks to pass.
- Block non-fast-forward updates.
- Block branch deletion.

## Required Checks

Target required checks:

- `backend-ci`
- `admin-ci`
- `ops-guard`

Important sequencing rule:

Required checks must exist on `main` before they are made required. Do not point
branch protection at a workflow that only exists on an unmerged PR. That locks
normal merging because GitHub cannot satisfy a required check that `main` does
not know how to run.

Safe rollout order:

1. Merge the CI workflow to `main` while the check is not required yet.
2. Confirm the workflow has run successfully on `main` at least once.
3. Add the check names to the branch protection ruleset.
4. Open a test PR and confirm the Merge button is blocked until the checks pass.

If this order is accidentally broken, use the emergency bypass flow below to
merge the CI bootstrap PR, then immediately restore the ruleset.

## Bypass Policy

Normal work must not bypass branch protection.

Emergency bypass should be allowed only for repository administrators and only
when production is broken or branch protection itself has locked normal
recovery.

Recommended safety-valve setting:

```text
bypass_actors:
  - actor_type: RepositoryRole
    actor_id: 5   # Admin
    bypass_mode: always
```

Do not enable broader bypasses. If this setting is not enabled, the owner can
still use `gh pr merge --admin` only when GitHub permits it for the repository;
otherwise the ruleset may lock recovery PRs until the ruleset is edited.

Allowed emergency command:

```bash
gh pr merge <pr-number> --admin --squash
```

Requirements after any `--admin` merge:

1. Add an incident note to `RUNBOOK.md`.
2. Include the PR number, reason for bypass, production impact, validation, and
   cleanup follow-up.
3. Verify `/health/detail`.
4. Re-check the ruleset and required checks.

Do not use local force push, direct push to `main`, or deletion/recreation of
protected branches as an emergency path.
