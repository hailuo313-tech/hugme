# D7-2 Alert Thresholds + Notification Design

Date: 2026-05-12
Owner: Codex AI
Status: ready for review; not enabled by default

## Goal

Define the first ERIS alerting slice on top of the D7-1 monitoring plan. This task adds Prometheus alert rules, an Alertmanager routing template, and operator-facing notification copy without sending real Discord or email alerts yet.

## Current State

- D7-1 monitoring assets exist under `/opt/eris/monitoring`.
- Prometheus and Grafana are templates only; they are not running.
- `/metrics` is not implemented yet, so application metric alerts are design-ready but inactive until D7 Phase B.
- `/health/detail` is live and returns `api/db/redis`.
- Stripe webhook handling is still a placeholder, so Stripe alert rules are marked as pending.

## Notification Channels

Recommended beta routing:

| Severity | Destination | Purpose |
|---|---|---|
| critical | Discord ops channel + email | Wake someone up or stop beta traffic |
| warning | Discord ops channel | Needs attention during the day |
| info | Dashboard only | Useful signal, not actionable yet |

Secrets required later:

- `DISCORD_WEBHOOK_URL`
- `ALERT_EMAIL_TO`
- SMTP host/user/password if email is enabled directly through Alertmanager

Do not store real notification secrets in repository files. Put them in `/opt/eris/.env` only when alert delivery is intentionally enabled.

Alertmanager does not expand `.env` values inside YAML by itself. To enable real delivery later, copy
`monitoring/alertmanager/receivers.example.yml` into a private deployment config and render it with the real secrets
outside Git.

## Core Alert Thresholds

| Alert | Severity | Expression intent | Duration | Action |
|---|---|---|---|---|
| `ErisApiDown` | critical | `up{job="eris-api"} == 0` | 2m | Check API container and Nginx proxy |
| `ErisPostgresDown` | critical | `up{job="eris-postgres"} == 0` | 2m | Check Postgres container and disk |
| `ErisRedisDown` | critical | `up{job="eris-redis"} == 0` | 2m | Check Redis container and password/env |
| `ErisApiHighErrorRate` | critical | 5xx rate > 2% | 5m | Inspect logs by trace_id and rollback if deploy-related |
| `ErisApiLatencyHigh` | warning | p95 HTTP latency > 1.5s | 10m | Inspect slow routes and database |
| `ErisTelegramWebhookFailing` | critical | webhook failure rate > 5% | 5m | Check BotFather webhook, `/api/v1/messages/inbound`, Telegram token |
| `ErisLlmFailureRateHigh` | warning | LLM failure rate > 5% | 10m | Check OpenRouter key/quota/provider status |
| `ErisLlmLatencyHigh` | warning | p95 LLM latency > 15s | 10m | Switch model/provider or degrade gracefully |
| `ErisP0HandoffOld` | critical | oldest P0 handoff > 5m | 3m | Human operator must claim task |
| `ErisHandoffBacklogHigh` | warning | open handoff tasks > 20 | 10m | Add operator capacity or pause risky flows |
| `ErisNotificationQueueStuck` | warning | oldest pending notification > 30m | 10m | Check D6 queue worker before enabling sends |
| `ErisNotificationFailureRateHigh` | warning | notification failed rate > 5% | 15m | Inspect Telegram send errors and opt-out gates |
| `ErisStripeWebhookFailure` | critical | Stripe webhook verification failures > 0 | 5m | Check `STRIPE_WEBHOOK_SECRET` and endpoint |
| `ErisMetricsMissing` | warning | expected app metric absent | 15m | Confirm `/metrics` and Prometheus scrape config |

## Error Category Mapping

The task asks to align thresholds with Appendix A.2 error codes. The Appendix A.2 source file is not present in this
repository yet, so the current rules use stable metric `result` categories that can map to A.2 once the contract lands:

| Metric result/category | Intended Appendix A.2 bucket |
|---|---|
| `failed` | generic service failure |
| `timeout` | upstream timeout |
| `signature_failed` | auth/signature validation failure |
| `blocked` | policy or eligibility block |
| `duplicate` | idempotency duplicate |
| `fallback` | degraded-mode success |

When Appendix A.2 is added, update `eris-alerts.yml` annotations with the exact error code names without changing the
alert names or receiver routes.

## Beta Alert Policy

- During beta, every critical alert should have a named human owner.
- Warning alerts should group for 5 minutes to reduce noise.
- Alerts must never include user identifiers, message text, tokens, or payment details.
- If notification sending is not live yet, alerts should stay dashboard-only.
- Stripe alerts become required before real money flows.

## Files Added

- `monitoring/alerts/eris-alerts.yml`
- `monitoring/alertmanager/alertmanager.yml`
- `monitoring/alertmanager/discord-message-template.md`
- `monitoring/alertmanager/email-message-template.md`
- `monitoring/alertmanager/receivers.example.yml`

`alertmanager.yml` intentionally routes all alerts to `dashboard-only` for now. Real Discord/email receivers should be added only when the team is ready to test notification delivery.

Files updated:

- `monitoring/prometheus.yml`
- `monitoring/docker-compose.monitoring.yml`

## Enablement Plan

1. Implement `/metrics` and application counters/gauges.
2. Start Prometheus/Grafana locally or behind SSH-only access.
3. Start Alertmanager with placeholder receiver.
4. Add real `DISCORD_WEBHOOK_URL` and/or SMTP credentials.
5. Send one test alert to verify formatting.
6. Only then enable beta alert delivery.

## Review Notes For Related Work

- PR #5 `chore/compose-pass-feature-flags`: accepted. It passes feature flags into the API container and is required for
  safe fallback behavior; no monitoring conflict.
- PR #6 `chore/compose-drop-version`: accepted. Dropping top-level compose `version` reduces Docker warning noise; no
  runtime behavior change.
- PR #7 `feat/silent-reactivation-scheduler`: accepted with D7 implication. Scheduler adds APScheduler and
  `SILENT_REACTIVATION_CRON`; D7 dashboards should track notification queue depth and stale pending tasks before real
  sends are enabled.
- SSH hardening and roadmap scp are treated as deployment facts, not source changes in this PR. They should not be
  reimplemented from this branch.

## D7-2 Acceptance Checklist

- [x] Critical and warning thresholds defined.
- [x] Prometheus alert rules created.
- [x] Alertmanager routing template created.
- [x] Discord notification copy template created.
- [x] Email notification copy template created.
- [x] Receiver enablement example created without real secrets.
- [x] Monitoring compose template updated for Alertmanager.
- [x] Active runtime left unchanged.
- [ ] Real Discord/email delivery enabled in a later task.
- [ ] Alert rules exercised after `/metrics` is implemented.
