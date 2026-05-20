# C-13 Grafana 大盘与告警规则走查

**任务：** C-13 — Grafana 大盘与告警规则走查  
**验收：** 核心指标均有告警  
**规范：** [`D7-1_MONITORING_DESIGN.md`](../D7-1_MONITORING_DESIGN.md)、[`D7-2_ALERTING_DESIGN.md`](../D7-2_ALERTING_DESIGN.md)

---

## 1. 核心指标 → 告警映射

| # | 核心指标 | 告警规则 |
|---|----------|----------|
| 1 | API HTTP | `ErisApiDown`, `ErisApiHighErrorRate`, `ErisApiLatencyHigh`, `ErisMetricsMissing` |
| 2 | Telegram 入站 | `ErisTelegramWebhookFailing` |
| 3 | LLM 流 | `ErisLlmFailureRateHigh`, `ErisLlmLatencyHigh` |
| 4 | Handoff 队列 | `ErisP0HandoffOld`, `ErisHandoffBacklogHigh` |
| 5 | 通知队列 | `ErisNotificationQueueStuck`, `ErisNotificationFailureRateHigh` |
| 6 | Stripe 计费 | `ErisStripeWebhookFailure` |

基础设施：`ErisPostgresDown`, `ErisRedisDown`

---

## 2. Grafana 大盘（ERIS MVP Overview）

| 面板 | PromQL 要点 |
|------|-------------|
| API Up | `up{job="eris-api"}` |
| API Requests | `eris_http_requests_total` |
| API p95 Latency | `eris_http_request_duration_seconds_bucket` |
| Telegram Webhook Events | `eris_telegram_webhook_events_total` |
| LLM Request Rate | `eris_llm_requests_total` |
| LLM p95 Latency | `eris_llm_request_duration_seconds_bucket` |
| Open Handoff Tasks | `eris_handoff_open_tasks` |
| Oldest Handoff Age | `eris_handoff_oldest_open_age_seconds` |
| Notification Queue | `eris_notification_tasks` |
| Oldest Pending Notification | `eris_notification_oldest_pending_age_seconds` |
| Stripe Webhooks | `eris_stripe_webhook_events_total` |

---

## 3. 人工走查步骤（生产/SSH）

```bash
cd /opt/eris/monitoring
docker compose -f docker-compose.monitoring.yml up -d
# Grafana: http://127.0.0.1:3001 (SSH 隧道)
# Prometheus: http://127.0.0.1:9090
# Alertmanager: http://127.0.0.1:9093
```

| # | 项 | 结果 | 备注 |
|---|-----|------|------|
| 1 | Prometheus Targets 全 UP | ☐ PASS ☐ FAIL | api / postgres-exporter / redis-exporter |
| 2 | Grafana 大盘 11 面板有数据或 No data（规则存在） | ☐ PASS ☐ FAIL | 见 §2 |
| 3 | Alertmanager 路由 critical→discord | ☐ PASS ☐ FAIL | 无 webhook 时仅 dashboard-only |
| 4 | `eris-alerts.yml` 14 条规则已加载 | ☐ PASS ☐ FAIL | Prometheus → Status → Rules |
| 5 | 核心 6 指标均有对应告警 | ☐ PASS ☐ FAIL | 见 §1 |
| 6 | 走查问题单关闭 | ☐ PASS ☐ FAIL | `C13_GRAFANA_ISSUES.md` |

---

## 4. 门禁

```powershell
.\scripts\check-c13-grafana-walkthrough.ps1
```

---

## 5. 签字

| 角色 | 姓名 | 日期 |
|------|------|------|
| 检验 | | |
| 运维确认 | | |

**结论：** ☐ 通过　☐ 不通过
