# D8 PR Gates

This is the lightweight D8 merge-gate policy for Cursor, Devin, Codex, and
human reviewers.

Current state (**C-02 / CUR-D8-01** — workflow is real):

- `.github/workflows/pr-required-gates.yml` runs on `pull_request` to `main` (and `workflow_dispatch`).
- **`admin-ci`**: `npm ci` → **`npm run lint`** (ESLint) → **`npm run typecheck`** (`tsc --noEmit`) → **`npm run build`** in `admin/`.
- **`backend-ci`**: pip install → **`ruff check`** → **`ruff format --check`** → **`mypy`** → `compileall` → **`pytest -q`** (config: `pyproject.toml`, `pytest.ini`).
- **`ops-guard`**: `RUNBOOK.md`, `docker-compose.yml`, **`docs/REPO_LAYOUT.md`**, **`pyproject.toml`**, compose layout; no tracked `admin/node_modules` or `admin/.next`; `bash -n` on `scripts/**/*.sh`.

PR 上三项 job 任一失败即不可合并（须在 GitHub 仓库 Settings → Branches 将 `管理员-ci`、`后端-ci`、`操作守卫` 设为 required checks）。

This document remains the **reviewer contract**; CI is the **automated minimum**.

## Current Check Name Mapping

| Job id in workflow | GitHub check display name currently seen on PRs | Current behavior | D8 risk |
| --- | --- | --- | --- |
| `admin-ci` | `管理员-ci` | `npm ci` + lint + typecheck + build | Fails on ESLint / TS / Next build |
| `backend-ci` | `后端-ci` | ruff + mypy + compileall + pytest | Fails on lint / types / tests |
| `ops-guard` | `操作守卫` | key files + no tracked admin artifacts + `bash -n` on `scripts/**/*.sh` | Fails on broken ops layout or committed `node_modules`/`.next` |

When repository Settings later enables required status checks, use the exact
check names GitHub shows on PRs. Avoid guessing from job ids if display names
change. Some Windows shells may render these Chinese names as mojibake; use the
GitHub PR UI as the source of truth.

## COD-D8-01 CI Replacement Acceptance Details

This section is the copy source for replacing the placeholder jobs in
`.github/workflows/pr-required-gates.yml`. Cursor can implement the workflow
from these details without inventing commands.

Global workflow rules:

- Trigger stays `pull_request` to `main`.
- `permissions: contents: read` stays unchanged.
- `concurrency` stays enabled with `cancel-in-progress: true`.
- Runner stays `ubuntu-latest` for all three jobs.
- Use built-in dependency caching from `actions/setup-python` and
  `actions/setup-node`; do not add a separate `actions/cache` step unless a
  measured cache miss proves it is needed.
- Do not enable branch-protection required checks until this real workflow has
  already landed on `main` and passed once on a fresh PR.

### `backend-ci`

Display name:

```yaml
name: 后端-ci
```

Exact setup and commands:

```yaml
steps:
  - uses: actions/checkout@v4

  - uses: actions/setup-python@v5
    with:
      python-version: "3.12"
      cache: pip
      cache-dependency-path: |
        app/requirements.txt
        requirements-dev.txt

  - name: Install backend dependencies
    run: |
      python -m pip install --upgrade pip
      python -m pip install -r app/requirements.txt -r requirements-dev.txt

  - name: Compile Python sources
    run: python -m compileall app tests

  - name: Run backend tests
    run: pytest -q
```

Cache strategy:

- Cache manager: `actions/setup-python@v5`.
- Cache key inputs: Python version plus `app/requirements.txt` and
  `requirements-dev.txt`.
- Do not cache `.venv`; CI installs into the runner Python environment.
- Do not cache `.pytest_cache`; test results must not influence later PRs.

Failure examples that must fail this job:

- `ModuleNotFoundError: No module named 'fastapi'`: dependency install is broken
  or `app/requirements.txt` was not installed.
- `zoneinfo._common.ZoneInfoNotFoundError`: `requirements-dev.txt` no longer
  provides the Windows/local test dependency `tzdata`, or tests now depend on a
  timezone database that is not declared.
- `SyntaxError` or import errors from `python -m compileall app tests`.
- Any failing test collected by `pytest -q`.

Windows dev setup compatibility:

- Compatible with `docs/WINDOWS_DEV_SETUP.md`: both use Python 3.12 and install
  `app/requirements.txt` plus `requirements-dev.txt`.
- CI uses Bash path separators (`app/requirements.txt`); Windows local docs use
  PowerShell path separators (`app\requirements.txt`). This is expected and is
  not a policy conflict.
- CI must not run `scripts/bootstrap_windows_dev.ps1`; that script is for local
  Windows bootstrap only.
- Do not use Python 3.14 in CI. The Windows guide documents wheel failures for
  `asyncpg` and `pydantic-core`; CI should avoid that class of failure by
  pinning Python 3.12.

### `admin-ci`

Display name:

```yaml
name: 管理员-ci
```

Exact setup and commands:

```yaml
steps:
  - uses: actions/checkout@v4

  - uses: actions/setup-node@v4
    with:
      node-version: "20"
      cache: npm
      cache-dependency-path: admin/package-lock.json

  - name: Install admin dependencies
    working-directory: admin
    run: npm ci

  - name: Build admin
    working-directory: admin
    run: npm run build

  - name: Lint admin
    working-directory: admin
    run: npm run lint
```

Cache strategy:

- Cache manager: `actions/setup-node@v4`.
- Cache key input: `admin/package-lock.json`.
- Do not cache `admin/node_modules`; `npm ci` must recreate it from the lockfile.
- Do not cache `admin/.next`; every PR must prove a fresh production build.

Failure examples that must fail this job:

- `npm ci` fails because `admin/package.json` and `admin/package-lock.json` are
  out of sync.
- `npm run build` fails on TypeScript, Next.js route, import, or basePath build
  errors.
- `npm run lint` fails on ESLint or Next lint violations.
- A PR commits generated files under `admin/node_modules/` or `admin/.next/`;
  `ops-guard` also catches this, but admin reviewers should treat it as a hard
  failure.

Windows dev setup compatibility:

- No conflict with `docs/WINDOWS_DEV_SETUP.md`; that document covers Python
  backend setup only.
- Node 20 is the CI baseline for admin. If a future Windows admin setup doc
  chooses another local Node version, update this section and the workflow in
  the same PR.

### `ops-guard`

Display name:

```yaml
name: 操作守卫
```

Exact setup and commands:

```yaml
steps:
  - uses: actions/checkout@v4
    with:
      fetch-depth: 0

  - name: List changed files
    run: git diff --name-only origin/${{ github.base_ref }}...HEAD > /tmp/changed_files

  - name: Reject generated admin artifacts
    shell: bash
    run: |
      if grep -E '(^|/)admin/(node_modules|\.next)/' /tmp/changed_files; then
        echo "Generated admin artifacts must not be committed" >&2
        exit 1
      fi

  - name: Check shell scripts
    shell: bash
    run: |
      shopt -s globstar nullglob
      scripts=(scripts/*.sh scripts/**/*.sh)
      if [ ${#scripts[@]} -gt 0 ]; then
        bash -n "${scripts[@]}"
      fi

  - name: Reject obvious live secrets
    shell: bash
    run: |
      if git grep -nE '(sk_live_[A-Za-z0-9]+|whsec_[A-Za-z0-9]+|xox[baprs]-[A-Za-z0-9-]+)' -- .; then
        echo "Possible live secret committed" >&2
        exit 1
      fi
```

Cache strategy:

- No dependency cache. This job only uses Git and Bash on `ubuntu-latest`.
- Do not install extra packages in this job.

Failure examples that must fail this job:

- A changed file path matches `admin/node_modules/**`.
- A changed file path matches `admin/.next/**`.
- `bash -n` reports syntax errors in any `scripts/**/*.sh` file.
- `git grep` finds an obvious live key pattern such as `sk_live_...`,
  `whsec_...`, or Slack-style `xox...` tokens.

Windows dev setup compatibility:

- No conflict with `docs/WINDOWS_DEV_SETUP.md`; `ops-guard` runs only in Linux
  CI and does not replace local Windows bootstrap instructions.
- Bash syntax checks are intentionally Linux-based because production scripts
  run on the AlmaLinux server, not in PowerShell.

### Required Check Names After Replacement

After the real workflow lands on `main`, open a fresh PR and copy the exact
check names from the GitHub PR UI. The expected names are:

| Job id | Expected GitHub check name | Required status check? |
| --- | --- | --- |
| `backend-ci` | `后端-ci` | Yes, after the real job passes on `main` |
| `admin-ci` | `管理员-ci` | Yes, after the real job passes on `main` |
| `ops-guard` | `操作守卫` | Yes, after the real job passes on `main` |

Do not treat a **pre-CUR-D8-01** placeholder run as proof. The acceptance run is
the first PR where all three jobs execute the real steps above.

## Manual D8 Gate Matrix

CI now runs the commands above on every PR to `main`. Reviewers should still use
the matrix below for **scope judgment** (targeted tests, migrations, deploy
notes). For non-obvious PRs, the PR body should list any **extra** verification
that CI does not cover (for example migration dry-runs or manual staging smoke).

| PR type | Examples | Required before review | Required before merge |
| --- | --- | --- | --- |
| Backend service/API | `app/**`, `tests/**`, memory/retrieval/scoring/payment/telegram | `python -m compileall app tests`; targeted `pytest` for touched area | `pytest -q` or documented reason plus reviewer approval |
| Admin frontend | `admin/**` | `cd admin && npm ci` when lockfile/deps changed; otherwise existing deps are okay; `npm run build` | `npm run build`; `npm run lint` if lint is configured and not blocked by known baseline |
| Database / migrations | `scripts/init.sql`, `scripts/migrations/**` | migration reviewed for idempotency, locking, backup, rollback; no production execution from PR | dry-run/read-only verification plan in PR; rollback documented |
| Ops / deploy / monitoring | `docker-compose.yml`, `deploy.sh`, `monitoring/**`, `.env.example`, `RUNBOOK.md` | syntax/config sanity where available; explicit deploy and rollback impact | reviewer confirms maintenance-window notes and no secret leakage |
| Docs only | `docs/**`, `README.md`, `RUNBOOK.md` | spell/scope check; links/commands plausible | no code test required, but CI must not be red |
| Workflow changes | `.github/workflows/**` | announce ownership first; no parallel edits | reviewer checks required-check names and lockout risk |

## Backend Gate Details

Use the smallest useful test set while developing, but do not merge with only a
happy-path smoke when shared behavior changed.

Recommended local commands:

```bash
python -m compileall app tests
pytest -q
```

Targeted examples:

```bash
pytest -q tests/test_memory_retriever.py
pytest -q tests/test_memory_writer.py
pytest -q tests/test_admin_conversations.py
pytest -q tests/test_stripe_webhook.py
```

Minimum expectations:

- New or changed service code has at least one happy path and one failure path
  test.
- Public API behavior changes include request/response or auth coverage.
- Any path that emits production logs keeps `trace_id` intact where applicable.
- If a full `pytest -q` run is skipped, the PR body must say why and list the
  targeted tests that did run.

Ruff status:

- Ruff is not currently configured in the repo baseline.
- Do not add ruff as a required D8 gate until a separate formatting/lint task
  lands configuration and fixes or suppresses baseline violations.

## Admin Gate Details

Recommended commands:

```bash
cd admin
npm run build
npm run lint
```

Rules:

- `npm run build` is the D8 minimum for any `admin/**` change.
- `npm run lint` is recommended. If Next lint is blocked by existing baseline or
  config issues, record the failure and do not hide it.
- Do not commit `admin/node_modules/` or `admin/.next/`.
- UI-only mock data must be clearly marked and must not look like real user
  scores in production admin routes.

## Ops And Migration Gate Details

For migration/index PRs:

- Explain whether SQL is safe to re-run.
- State whether it requires autocommit, `CONCURRENTLY`, or a maintenance window.
- Include read-only verification SQL.
- Include rollback or cleanup commands.
- Confirm a fresh backup exists before production execution.

For deployment/config PRs:

- Say whether a container rebuild is required.
- Say whether `.env.example` changed.
- Say how to roll back.
- Never include real secrets, tokens, passwords, or copied `.env` values.

## PR Body Checklist

Align with `AGENTS.md` section 6. Keep this compact in every PR:

```markdown
## Related task
- D8-x / ticket link:

## Summary
- Files changed:
- Behavior changed:

## Verification
- [ ] Backend: `python -m compileall app tests`
- [ ] Backend: `pytest -q` or targeted tests:
- [ ] Admin: `npm run build`
- [ ] Admin: `npm run lint` or known reason skipped:
- [ ] Ops/migration: backup, rollback, verification documented:
- [ ] Docs-only: no runtime test needed:

## Deploy impact
- Env changes:
- DB migration:
- Rebuild/restart:
- Rollback:
```

Only keep the lines that apply. Do not claim a command ran if it did not.

## Two-Phase CI Plan

### Phase 1: Manual policy (still in force)

- Reviewers use this document for migrations, deploy risk, and anything CI does
  not model (secrets, production-only smoke, data backfills).
- The release owner keeps merge order: schema/indexes, backend API, admin UI,
  ops/docs, deploy.

### Phase 2: Automated gates (**landed** — CUR-D8-01)

The workflow `.github/workflows/pr-required-gates.yml` now runs real commands
(see **Current state** at the top of this file). The YAML excerpts under
**COD-D8-01 CI Replacement Acceptance Details** remain the human-readable spec;
implementation may differ slightly (for example `compileall -q`, `find … bash -n`
instead of `globstar`).

**Optional follow-ups** (not in CI yet): `npm run lint` in `admin-ci`;
`ops-guard` patterns for live secrets (`git grep` heuristics from the COD-D8-01
draft); `deploy.sh` guard when that script exists on `main`.

Do not enable **branch protection required checks** in GitHub Settings until:

- This workflow is merged to `main` and has gone **green on at least one real PR**.
- The exact required check names are copied from the GitHub PR UI (display names
  may differ from job ids).
- There is an agreed emergency/admin bypass procedure.

## Merge Rhythm

Keep D8 merges boring:

1. One production-affecting merge line at a time.
2. Rebase stale branches before review.
3. Treat a green PR gate run as the automated minimum; still require human
   review for migrations and deploy risk.
4. Do not admin-merge except for documented production incidents or protection
   lockout.
5. After merge, deploy from clean `main` only during a maintenance window.
