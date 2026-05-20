"""C-13 / D7: Grafana dashboard and alerting walkthrough contract."""

from __future__ import annotations

# D7-1 six launch-blocking visibility metrics
CORE_METRICS = (
    "api_http",
    "telegram_ingress",
    "llm_flow",
    "handoff_queue",
    "notification_queue",
    "stripe_billing",
)

# Each core metric must map to at least one alert in eris-alerts.yml
CORE_METRIC_ALERTS: dict[str, tuple[str, ...]] = {
    "api_http": ("ErisApiDown", "ErisApiHighErrorRate", "ErisApiLatencyHigh", "ErisMetricsMissing"),
    "telegram_ingress": ("ErisTelegramWebhookFailing",),
    "llm_flow": ("ErisLlmFailureRateHigh", "ErisLlmLatencyHigh"),
    "handoff_queue": ("ErisP0HandoffOld", "ErisHandoffBacklogHigh"),
    "notification_queue": ("ErisNotificationQueueStuck", "ErisNotificationFailureRateHigh"),
    "stripe_billing": ("ErisStripeWebhookFailure",),
}

INFRA_ALERTS = ("ErisPostgresDown", "ErisRedisDown")

REQUIRED_ALERTS = tuple(
    sorted(
        {
            *INFRA_ALERTS,
            *(a for group in CORE_METRIC_ALERTS.values() for a in group),
        }
    )
)

DASHBOARD_REQUIRED_PANELS = (
    "API Up",
    "API Requests",
    "API p95 Latency",
    "Telegram Webhook Events",
    "LLM Request Rate",
    "LLM p95 Latency",
    "Open Handoff Tasks",
    "Oldest Handoff Age",
    "Notification Queue",
    "Oldest Pending Notification",
    "Stripe Webhooks",
)

MONITORING_FILES = (
    "monitoring/prometheus.yml",
    "monitoring/alerts/eris-alerts.yml",
    "monitoring/grafana-dashboard-eris-mvp.json",
    "monitoring/docker-compose.monitoring.yml",
    "monitoring/alertmanager/alertmanager.yml",
    "monitoring/grafana/provisioning/datasources/prometheus.yml",
    "monitoring/grafana/provisioning/dashboards/eris.yml",
)

C13_CHECKLIST_IDS = (
    "C13-01",
    "C13-02",
    "C13-03",
    "C13-04",
    "C13-05",
    "C13-06",
    "C13-07",
    "C13-08",
)


def integration_contract() -> dict:
    return {
        "core_metrics": list(CORE_METRICS),
        "required_alerts": list(REQUIRED_ALERTS),
        "dashboard_panels": list(DASHBOARD_REQUIRED_PANELS),
        "monitoring_files": list(MONITORING_FILES),
        "checklist_ids": list(C13_CHECKLIST_IDS),
    }
