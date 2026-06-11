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
        "SILENT_REACTIVATION_ENABLED",
        "SILENT_REACTIVATION_CRON",
        "NOTIFICATION_SENDER_ENABLED",
        "NOTIFICATION_SENDER_POLL_SECONDS",
        "NOTIFICATION_SENDER_SCHEDULER_MAX_INSTANCES",
        "MESSAGE_SCHEDULE_ENABLED",
        "MESSAGE_SCHEDULE_POLL_SECONDS",
        "MESSAGE_SCHEDULE_SCHEDULER_MAX_INSTANCES",
        "AUTO_DELIVERY_ENABLED",
        "AUTO_DELIVERY_POLL_SECONDS",
        "AUTO_DELIVERY_SCHEDULER_MAX_INSTANCES",
        "ARCHIVE_WORKER_ENABLED",
        "ARCHIVE_WORKER_POLL_SECONDS",
        "ARCHIVE_WORKER_SCHEDULER_MAX_INSTANCES",
        "APP_DOWNLOAD_NURTURE_ENABLED",
        "APP_DOWNLOAD_FIRST_IDLE_SECONDS",
        "APP_DOWNLOAD_SECOND_NO_CLICK_SECONDS",
        "APP_DOWNLOAD_WARM_NO_CLICK_SECONDS",
        "APP_DOWNLOAD_CLICK_NO_DOWNLOAD_SECONDS",
        "APP_DOWNLOAD_SILENT_30M_SECONDS",
        "APP_DOWNLOAD_SILENT_24H_SECONDS",
    }

    missing = [name for name in sorted(required) if f"{name}:" not in compose]
    assert missing == []


def test_proactive_delivery_workers_are_enabled_by_default_in_compose():
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "SILENT_REACTIVATION_ENABLED: ${SILENT_REACTIVATION_ENABLED:-1}" in compose
    assert "NOTIFICATION_SENDER_ENABLED: ${NOTIFICATION_SENDER_ENABLED:-1}" in compose
    assert "MESSAGE_SCHEDULE_ENABLED: ${MESSAGE_SCHEDULE_ENABLED:-1}" in compose
    assert "AUTO_DELIVERY_ENABLED: ${AUTO_DELIVERY_ENABLED:-1}" in compose
