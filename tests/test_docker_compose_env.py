"""Ops guard: compose must pass feature flags into the API container."""
from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_d4_4_and_policy_env_vars_are_passed_to_api_container():
    """D4-4-OPS depends on compose env passthrough, not just .env keys.

    Docker Compose reads the repo ``.env`` for variable substitution, but it does
    not inject every key into a service automatically.  Keep this guard close to
    the incident that left production with ``profile_score.scheduler.disabled``.
    """
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    required = {
        "SCORE_WORKER_ENABLED",
        "SCORE_WORKER_POLL_SECONDS",
        "SCORE_WORKER_SCHEDULER_MAX_INSTANCES",
        "SCORE_INITIATION_LOOKBACK_DAYS",
        "SCORE_INITIATION_CAP_MESSAGES",
        "SCORE_PROFILE_MIN_UPDATE_DELTA",
        "TRIGGER_THRESHOLD_BASE",
        "TRIGGER_THRESHOLD_PIVOT",
        "TRIGGER_THRESHOLD_K",
        "TRIGGER_THRESHOLD_FLOOR",
        "TRIGGER_THRESHOLD_CEIL",
        "POLICY_SERVICE_ENABLED",
        "POLICY_RISK_SCORE_THRESHOLD",
        "POLICY_LONELINESS_THRESHOLD",
        "POLICY_VIP_LEVEL_THRESHOLD",
        "POLICY_HANDOFF_COUNT_THRESHOLD",
    }

    missing = [name for name in sorted(required) if f"{name}:" not in compose]
    assert missing == []
