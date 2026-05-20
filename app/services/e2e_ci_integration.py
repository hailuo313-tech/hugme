"""C-12 / P5: E2E scripts and CI nightly integration contract."""

from __future__ import annotations

# Nightly UTC 06:00 — after PR gates; stability tracked for 3 consecutive greens
NIGHTLY_CRON_UTC = "0 6 * * *"
NIGHTLY_STABILITY_DAYS = 3

E2E_FULL_SCRIPT = "scripts/e2e/run.sh"
E2E_SMOKE_SCRIPT = "scripts/e2e/smoke.sh"
PERF_LOAD_SCRIPT = "scripts/perf/d8_2_retrieval_load.py"

PR_WORKFLOW = ".github/workflows/pr-required-gates.yml"
NIGHTLY_WORKFLOW = ".github/workflows/nightly-e2e-ci.yml"

# D7-3 full path (local/staging); CI nightly runs smoke profile only
E2E_FULL_STEPS = (
    "preflight /health/detail",
    "telegram register + onboarding",
    "multi-round chat (default 50)",
    "handoff trigger + lock + reply + return-ai",
    "stripe checkout order create",
)

E2E_SMOKE_STEPS = (
    "preflight /health/detail",
    "telegram register + onboarding",
    "chat rounds=3 (E2E_CHAT_ROUNDS)",
    "handoff trigger + lock + reply + return-ai",
    "stripe skipped (E2E_SKIP_STRIPE)",
)

PERF_SCOPE = (
    "POST /api/v1/users/{user_id}/memories/retrieve",
    "client P95 probe; requires ERIS_OPERATOR_JWT + ERIS_USER_ID",
    "explicitly outside PR CI — staging/production evidence only",
)

CI_JOBS = (
    "admin-ci",
    "backend-ci",
    "ops-guard",
    "c12-audit",
    "e2e-smoke",
)

C12_CHECKLIST_IDS = (
    "C12-01",  # e2e run.sh reviewed + bash -n
    "C12-02",  # e2e smoke.sh CI profile
    "C12-03",  # perf script scoped outside CI
    "C12-04",  # pr-required-gates.yml
    "C12-05",  # nightly-e2e-ci.yml schedule
    "C12-06",  # 3-day stability tracker artifact
    "C12-07",  # LLM_ECHO_FALLBACK documented for CI
    "C12-08",  # handoff path in e2e smoke
)


def integration_contract() -> dict:
    return {
        "nightly_cron_utc": NIGHTLY_CRON_UTC,
        "nightly_stability_days": NIGHTLY_STABILITY_DAYS,
        "e2e_full_script": E2E_FULL_SCRIPT,
        "e2e_smoke_script": E2E_SMOKE_SCRIPT,
        "perf_load_script": PERF_LOAD_SCRIPT,
        "pr_workflow": PR_WORKFLOW,
        "nightly_workflow": NIGHTLY_WORKFLOW,
        "e2e_full_steps": list(E2E_FULL_STEPS),
        "e2e_smoke_steps": list(E2E_SMOKE_STEPS),
        "perf_scope": list(PERF_SCOPE),
        "ci_jobs": list(CI_JOBS),
        "checklist_ids": list(C12_CHECKLIST_IDS),
    }
