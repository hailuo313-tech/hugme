"""C-14: Pre-launch code review and architecture consistency final inspection."""

from __future__ import annotations

# docs/REPO_LAYOUT.md canonical paths
CANONICAL_PATHS = (
    "app/main.py",
    "app/api/",
    "app/services/",
    "admin/",
    "scripts/",
    "tests/",
    "docs/",
    "ops/",
    "monitoring/",
    "fixtures/",
    "docker-compose.yml",
    "AGENTS.md",
    "RUNBOOK.md",
    "docs/REPO_LAYOUT.md",
)

FORBIDDEN_TOP_LEVEL_DIRS = ("gateway", "ws", "worker", "dashboard")

REQUIRED_COMPOSE_SERVICES = ("api", "postgres", "redis")

PR_GATE_JOBS = ("admin-ci", "backend-ci", "ops-guard")

# Cursor inspection deliverables (C-01 .. C-13) archived on main
CURSOR_DELIVERABLES: dict[str, tuple[str, ...]] = {
    "C-01": ("docs/REPO_LAYOUT.md", "AGENTS.md"),
    "C-02": (".github/workflows/pr-required-gates.yml",),
    "C-03": (".env.template",),
    "C-04": ("docs/CONTRACT_REVIEW_C04.md", "docs/schema_spec.json"),
    "C-05": ("docs/LEVEL_ENGINE_REVIEW_C05.md",),
    "C-15": ("docs/MTProto_SECURITY_REVIEW_C15.md",),
    "C-06": ("docs/C06_INSPECTION_REPORT.md",),
    "C-07": ("docs/C07_INSPECTION_REPORT.md",),
    "C-08": ("docs/C08_INSPECTION_REPORT.md",),
    "C-09": ("docs/C09_INSPECTION_REPORT.md", "docs/ws_protocol.md"),
    "C-10": (
        "docs/C10_INSPECTION_REPORT.md",
        "docs/C10_DASHBOARD_CHECKLIST_SIGNOFF.md",
    ),
    "C-11": (
        "docs/C11_INSPECTION_REPORT.md",
        "fixtures/c11_ux_checklist.json",
    ),
    "C-12": (
        "docs/C12_INSPECTION_REPORT.md",
        "fixtures/c12_nightly_stability.json",
        ".github/workflows/nightly-e2e-ci.yml",
    ),
    "C-13": (
        "docs/C13_INSPECTION_REPORT.md",
        "app/services/grafana_integration.py",
        "monitoring/alerts/eris-alerts.yml",
    ),
}

# business-flow.html baseline:true for completed cursor/human gates before C-14
BASELINE_TASK_IDS = (
    "C-01",
    "C-02",
    "C-03",
    "C-04",
    "C-05",
    "C-06",
    "C-07",
    "C-08",
    "C-09",
    "C-10",
    "C-11",
    "C-13",
    "C-15",
    "H-01",
    "H-02",
)

C14_CHECKLIST_IDS = (
    "C14-01",
    "C14-02",
    "C14-03",
    "C14-04",
    "C14-05",
    "C14-06",
    "C14-07",
    "C14-08",
    "C14-09",
    "C14-10",
)


def integration_contract() -> dict:
    return {
        "canonical_paths": list(CANONICAL_PATHS),
        "forbidden_top_level_dirs": list(FORBIDDEN_TOP_LEVEL_DIRS),
        "compose_services": list(REQUIRED_COMPOSE_SERVICES),
        "pr_gate_jobs": list(PR_GATE_JOBS),
        "cursor_deliverables": {k: list(v) for k, v in CURSOR_DELIVERABLES.items()},
        "baseline_task_ids": list(BASELINE_TASK_IDS),
        "checklist_ids": list(C14_CHECKLIST_IDS),
    }
