# Codex Parallel Baseline

Scope: read-only inventory for CI, deployment smoke, environment variables, and
merge discipline. This document intentionally does not change `admin/**`,
business APIs, or `.github/workflows/*.yml`.

Generated from repo tip on 2026-05-16 (reconcile with `main` after each release).

## Workflow Inventory

| File | Workflow name | Trigger | Branch filter | Jobs / check names | Notes |
| --- | --- | --- | --- | --- | --- |
| `.github/workflows/pr-required-gates.yml` | `PR required gates` | `pull_request` | `main` only | job ids: `admin-ci`, `backend-ci`, `ops-guard`; display names may render as mojibake Chinese in some clients | No `push` trigger. No `release/*` trigger. **CUR-D8-01:** `admin-ci` runs `npm ci` + `npm run build`; `backend-ci` runs Python 3.12 + `compileall` + `pytest -q`; `ops-guard` runs file/layout + `bash -n` checks (see `docs/PR_GATES_D8.md`). |

### Required Checks / Branch Protection

Live GitHub ruleset readout:

- Ruleset: `Protect main and release branches` (`id=16345617`)
- Enforcement: `active`
- Applies to: `refs/heads/main`, `refs/heads/release/*`
- Pull request required: yes
- Required approvals: `1`
- Stale approvals dismissed: yes
- Review thread resolution required: yes
- Direct deletion blocked: yes
- Non-fast-forward / force push blocked: yes
- Bypass actors: none
- Required status checks: none in the live ruleset readout

Risks to reconcile before tightening settings:

- The workflow exists, but required status checks are not currently active in
  the live ruleset. PRs can still be blocked by review, but not by CI.
- If Settings later adds required checks, use the GitHub check names that
  actually appear on PRs. The job ids are `admin-ci`, `backend-ci`, and
  `ops-guard`; the display names are currently mojibake and should not be used
  blindly as required check labels.
- `release/*` is protected by the ruleset, but the current workflow only runs
  for PRs targeting `main`.
- After **CUR-D8-01** lands on `main`, smoke a fresh PR: if all three jobs are
  green, the repo owner may enable them as required checks (still follow
  `docs/PR_GATES_D8.md` for exact names from the PR UI).

## Minimum Post-Deploy Smoke

Run after every production deploy or rollback. These steps are intentionally
small enough to finish during a maintenance window.

```bash
cd /opt/eris

# 1. Health, external and local.
curl -fsS https://hugme2.com/health/detail
curl -fsS http://127.0.0.1:8000/health/detail

# 2. Admin login. Do not print or paste the password into logs.
TOKEN=$(curl -fsS -X POST http://127.0.0.1:8000/api/v1/admin/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"YOUR_PASSWORD"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

# 3. One protected read API.
curl -fsS -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/v1/admin/conversations?page=1&page_size=5" \
  | python3 -m json.tool

# 4. Negative auth check for the same read surface.
curl -i http://127.0.0.1:8000/api/v1/admin/conversations

# 5. Ops static roadmap (./docs bind mount → /ops/*.html)
curl -fsS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/ops/eris-roadmap.html
```

Expected:

- `/health/detail` returns `{"api":"ok","db":"ok","redis":"ok"}`.
- Admin login returns a JWT.
- Protected read API returns JSON with `items`, `total`, `page`, and
  `page_size`.
- Unauthenticated admin read returns `401`, not `200`.
- `/ops/eris-roadmap.html` returns `200`.

Optional beta smoke:

```bash
API_BASE=http://127.0.0.1:8000 bash scripts/e2e/run.sh
```

## Environment Variable Inventory

| Variable | Purpose | Sensitive | Production required | Memory / loneliness relevance |
| --- | --- | --- | --- | --- |
| `POSTGRES_DB` | Postgres database name for the compose service | No | Yes for compose | Stores all user/profile/memory data |
| `POSTGRES_USER` | Postgres username for the compose service | No | Yes for compose | Stores all user/profile/memory data |
| `POSTGRES_PASSWORD` | Postgres password for compose and `DATABASE_URL` | Yes | Yes | Stores all user/profile/memory data |
| `DATABASE_URL` | Async SQLAlchemy URL read by `Settings` | Yes | Yes in the API container; compose derives it from Postgres vars | Directly required by memory writer/retriever and score reads |
| `REDIS_PASSWORD` | Redis password for the compose service | Yes | Yes for compose | Recent conversation context lives in Redis |
| `REDIS_URL` | Redis connection URL read by `Settings` | Yes | Yes in the API container; compose derives it from `REDIS_PASSWORD` | Recent context affects prompt assembly |
| `SECRET_KEY` | Admin JWT signing key | Yes | Yes | Required for protected admin smoke and operator auth |
| `OPENROUTER_API_KEY` | Chat LLM provider key | Yes | Yes for AI replies | Needed before memory writer can score via LLM route fallback |
| `TELEGRAM_BOT_TOKEN` | Telegram bot API token | Yes | Yes for Telegram production | Required for beta user entry |
| `LLM_ECHO_FALLBACK` | Allows echo fallback when LLM fails | No | Optional; should normally be false in prod | Not memory-specific |
| `MEMORY_WRITE_ENABLED` | Enables D3-3 async memory writer | No | Yes if memory creation is expected | Memory creation gate |
| `LLM_MEMORY_MODEL` | Model used by the memory writer scoring call | No | Recommended | Memory quality and cost |
| `MEMORY_IMPORTANCE_THRESHOLD` | Minimum score before writing a memory | No | Recommended | Memory write volume and retrieval quality |
| `EMBEDDING_WORKER_ENABLED` | Enables D3-4 async embedding backfill | No | Yes if D4 retrieval should use vectors | Memory retrieval readiness |
| `OPENAI_API_KEY` | Direct OpenAI key for embeddings | Yes | Yes for embedding worker/vector retrieval | Required for embeddings and D4 retrieval quality |
| `EMBEDDING_MODEL` | Embedding model name | No | Recommended; must match vector dimension | Must remain 1536-dim unless schema changes |
| `EMBEDDING_BATCH_SIZE` | Embedding worker batch size | No | Optional | Backfill throughput |
| `EMBEDDING_POLL_SECONDS` | Embedding worker interval | No | Optional | Backfill latency |
| `SILENT_REACTIVATION_ENABLED` | Enables silent reactivation scan/write path | No | Optional; false until ready | Related to retention, not D4 scoring |
| `SILENT_REACTIVATION_CRON` | UTC crontab for reactivation scheduler | No | Optional | Related to retention |
| `STRIPE_PUBLISHABLE_KEY` | Stripe frontend/test publishable key | No | Required for payment UI flows | Not memory-specific |
| `STRIPE_SECRET_KEY` | Stripe Checkout secret key | Yes | Required for Checkout | Not memory-specific |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret | Yes | Required for webhook processing | Not memory-specific |
| `STRIPE_SUCCESS_URL` | Checkout success redirect URL | No | Recommended | Not memory-specific |
| `STRIPE_CANCEL_URL` | Checkout cancel redirect URL | No | Recommended | Not memory-specific |
| `GRAFANA_ADMIN_USER` | Grafana bootstrap username | No | Required only when Grafana is deployed | Observability |
| `GRAFANA_ADMIN_PASSWORD` | Grafana bootstrap password | Yes | Required only when Grafana is deployed | Observability |
| `DISCORD_WEBHOOK_URL` | Alertmanager Discord receiver URL | Yes | Required only when Discord alerts are enabled | Observability |
| `ENV` | Runtime environment marker | No | Recommended | Not memory-specific |
| `MEMORY_RETRIEVE_IN_PROMPT` | When true, `generate_reply` calls `memory_retriever.retrieve` and fills L6 | No | Optional; prod semantic memory needs `OPENAI_API_KEY` | D4-2 |
| `MEMORY_RETRIEVE_TOP_K` / `MEMORY_RETRIEVE_K_CANDIDATES` | Injected hit count / SQL candidate pool | No | Optional | D4-2 |
| `MEMORY_CONSISTENCY_ENABLED` | Task 9: rule-filter conflicting hits before L6 | No | Optional (default true in `Settings`) | D4-2 |
| `MEMORY_CONSISTENCY_LLM_MAX_OUTPUT_TOKENS` | Reserved cap for optional LLM double-check (`0` = off) | No | Optional | D4-2 |
| `LONELINESS_REFRESH_ENABLED` | When true, orchestrator calls `refresh_loneliness_score` before retrieve | No | Optional | D4-3 |
| `LONELINESS_*` (lookback/clamps/decay/utterance) | Tunables for loneliness updater | No | Optional | D4-3 / D4-4 |
| `SCORE_WORKER_ENABLED` | Enables profile score scheduler/worker | No | Optional; default false | D4-4 |

### D4-2 / D4-3 / Compose: reconciled notes

- **`app/core/config.py` + `.env.example`** now include `MEMORY_RETRIEVE_*`, `MEMORY_CONSISTENCY_*`,
  `LONELINESS_*`, and score-worker keys. **`app/services/llm_orchestrator.py`** calls
  `refresh_loneliness_score` (D4-3) before `memory_retrieve` (D4-2) when enabled.
- **`docker-compose.yml`** still lists only a subset under `api.environment` (DB/Redis/LLM/Telegram/Silent/Stripe/ENV/OPS).
  Pydantic `Settings` reads `env_file='.env'` **inside the built image** unless you mount a host `.env` or extend compose
  to pass `MEMORY_*` / `LONELINESS_*` / `OPENAI_API_KEY` explicitly. Before assuming prod overrides work, **`docker exec eris-api env | grep -E 'MEMORY|LONELINESS|OPENAI'`**.

Optional post-deploy check for static roadmap (bind-mounted `./docs`):

```bash
curl -fsS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/ops/eris-roadmap.html
```

## Merge And Release Discipline

1. Merge to `main` only through PR review; no direct push, force push, or
   deletion on protected branches.
2. Keep one production merge/deploy line active at a time; rebase or close
   stale stacked PRs before merging.
3. Do not mark CI checks as required until the workflow exists on `main`, runs
   real checks, and has stable check names.
4. Production `git pull`/deploy should happen only in a maintenance window, from
   clean `main`, and with a fresh backup available.
5. Any emergency `--admin` merge must leave an incident note in the runbook or
   release notes immediately after the fire is out.

## Handoff Notes For Devin Interface Gap Table

When Devin publishes the admin/interface gap table, cross-check:

- Which endpoints return private user data without `require_operator`.
- Which admin reads have no negative auth smoke.
- Which D4-2 / D4-3 env names are real `Settings` fields (see `app/core/config.py`) versus compose-only gaps.
- Which PRs need CI once `admin-ci`, `backend-ci`, and `ops-guard` become real
  required checks.
