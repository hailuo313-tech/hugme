# ERIS Ops Governance

This document turns the branch and production safety rules into operating
policy. It exists because v0.1.0 exposed three avoidable failure modes:

1. A hotfix was merged before its parent feature PR, breaking merge order.
2. Production was built from a feature branch instead of `main`.
3. A feature branch was accidentally based on another feature branch and
   carried unrelated files into its PR.

## 1. Branch Policy

Protected branches:

- `main`
- `release/*`

Rules:

- No direct pushes.
- No force pushes.
- No branch deletions.
- Every change must enter through a pull request.
- Every PR needs at least one approval.
- Stale approvals are dismissed after new commits.
- Conversations must be resolved before merge.
- Required CI checks must pass.
- Branches must be up to date before merge.

Emergency repository administrators may bypass this only to recover a broken
production incident or a broken branch-protection rollout. Daily merges must use
the normal PR path. Any bypass must be written up in `RUNBOOK.md`.

Whether `RepositoryRole:Admin` is configured as a GitHub ruleset bypass actor is
a repository-owner decision. If it is enabled, it is only a firebreak for
production incidents and branch-protection lockouts, not a normal merge path.

The detailed GitHub settings live in `.github/branch-protection.md`.

## 2. PR Base Rules

Every feature, fix, docs, and release branch must be based on current
`origin/main` unless the task explicitly says otherwise.

Before opening a PR:

```bash
git fetch origin
git merge-base --is-ancestor origin/main HEAD
git diff --name-only origin/main...HEAD
```

The diff must contain only files owned by the task. If unrelated files appear,
stop and rebuild the branch from `origin/main`.

Do not stack PRs without writing this in the PR body:

```text
Stacked on: #<parent-pr>
Do not merge before: #<parent-pr>
```

If a child PR fixes code introduced by an unmerged parent PR, it must target the
parent branch, not `main`.

## 3. Merge Order

Use this order for MVP work:

```text
DB schema -> Telegram -> LLM -> Memory -> Admin -> Payment -> E2E -> Release
```

Hotfixes are allowed ahead of order only when production is down. A hotfix PR
must include:

- Why this is an incident.
- Which feature PR or release introduced it.
- How production was verified.
- Follow-up cleanup if the hotfix bypassed the normal order.

## 4. Production Deploy Rule

Production deploys must use `/opt/eris/deploy.sh`.

Do not run these directly for production deploys:

```bash
git checkout <feature-branch>
git pull
docker compose up -d --build api
```

`deploy.sh` refuses to deploy unless all are true:

- Current branch is `main`.
- Working tree is clean, including untracked files.
- Pull from `origin/main` can fast-forward cleanly.
- API health check passes after rebuild.

Tagged-release enforcement is available in `deploy.sh`; uncomment it when the
team wants production to deploy only exact release tags.

## 5. Required CI

GitHub branch rules require these checks:

- `backend-ci`: Python 3.9 syntax check and pytest.
- `admin-ci`: Next.js admin build.
- `ops-guard`: deploy guard and generated-artifact checks.

The Python version is intentionally 3.9 because production currently runs
Python 3.9. This prevents syntax that passes locally on newer Python versions
from reaching production.

Required-check rollout rule:

```text
CI workflow first -> merge to main -> observe green run on main -> mark required.
```

Never mark a check as required while that workflow exists only on an unmerged PR.
That creates a deadlock where normal PR merges are blocked by a required check
that `main` cannot yet produce.

If this happens, the only legal escape hatch is an admin merge of the CI
bootstrap PR:

```bash
gh pr merge <pr-number> --admin --squash
```

After any `--admin` merge, add an incident note to `RUNBOOK.md` with the PR
number, reason, production impact, validation, and cleanup follow-up.

## 6. Acceptance Tests

After this policy is enabled:

- Direct pushes to `main` and `release/*` are rejected by GitHub.
- Force pushes to `main` and `release/*` are rejected by GitHub.
- Merge buttons stay blocked until all required CI checks pass.
- `/opt/eris/deploy.sh` refuses deployment from any branch other than `main`.
- `/opt/eris/deploy.sh` refuses deployment when the working tree is dirty.
