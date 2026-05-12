# D7-1 Prometheus + Grafana Monitoring Design

Date: 2026-05-12
Owner: Codex AI
Status: ready for review; not enabled by default

## Goal

Define the first production monitoring slice for the ERIS MVP without changing runtime behavior. This package gives the team a Prometheus scrape plan, a Grafana dashboard draft, and the six core metrics that should be treated as launch-blocking visibility.

## Current State

- API runs as `eris-api` behind Nginx at `https://hugme2.com`.
- Health endpoints exist at `/health` and `/health/detail`.
- Structured JSON logs include `trace_id`, route, status, and duration.
- Notification queue APIs exist under `/api/v1/notifications`.
- Operator WebSocket exists at `/ws/operators/tasks`.
- Stripe webhook is still a placeholder, so payment metrics are marked as planned until real event handling lands.
- No Prometheus, Grafana, or `/metrics` endpoint is currently enabled.

## Six Core Metrics

| # | Metric | Source | Why it matters | MVP target |
|---|---|---|---|---|
| 1 | API request rate, latency, and error rate by route | FastAPI middleware or logs | Detect broken deploys and slow endpoints | p95 < 800 ms for normal API routes, 5xx < 1% |
| 2 | Telegram inbound success, duplicate, and failure count | `telegram.py`, `messages.py`, logs | Confirms the main acquisition channel is working | webhook 2xx > 99%, duplicate hit visible |
| 3 | AI request success, latency, and cost/token counters | `services/llm.py`, logs | Controls the most expensive and user-visible dependency | p95 < 10s, failures < 3% |
| 4 | Handoff queue depth, oldest age, and P0/P1 count | `handoff_tasks` table | Keeps human escalation from silently backing up | oldest open P0 < 5 minutes |
| 5 | Notification queue depth, oldest age, sent/failed/cancelled counts | `notification_tasks` table | Proves D6 silent reactivation is safe and inspectable | pending age < 30 minutes, failed < 5% |
| 6 | Billing/Stripe webhook received, verified, and failed count | `payments.py`, Stripe logs | Payments must be auditable before beta billing | planned until real Stripe verification lands |

Supporting infrastructure metrics:

- API container up/down and restart count.
- Postgres health and connection errors.
- Redis health and command errors.
- Nginx 4xx/5xx and TLS certificate expiry.
- WebSocket connected operators and disconnects.

## Recommended Metric Names

Application metrics to add when `/metrics` is implemented:

- `eris_http_requests_total{method,path,status}`
- `eris_http_request_duration_seconds_bucket{method,path,status}`
- `eris_telegram_webhook_events_total{result}`
- `eris_inbound_messages_total{channel,result}`
- `eris_llm_requests_total{provider,model,result}`
- `eris_llm_request_duration_seconds_bucket{provider,model,result}`
- `eris_llm_tokens_total{provider,model,type}`
- `eris_handoff_open_tasks{priority,status}`
- `eris_handoff_oldest_open_age_seconds{priority}`
- `eris_notification_tasks{status,type,channel}`
- `eris_notification_oldest_pending_age_seconds{type,channel}`
- `eris_notification_sends_total{type,channel,result}`
- `eris_stripe_webhook_events_total{event_type,result}`
- `eris_ws_operator_connections{state}`

Database-backed gauges can be exported by either:

1. A small API `/metrics` collector that runs SQL queries on scrape.
2. A separate exporter later, if query load becomes a concern.

For MVP, option 1 is acceptable if queries stay indexed and cheap.

## Dashboard Layout

Grafana dashboard: `ERIS MVP Overview`

Rows:

1. Service health
   - API up
   - Postgres up
   - Redis up
   - API 5xx rate
2. User ingress
   - Telegram webhook rate
   - Inbound message accepted vs blocked
   - Idempotency duplicate hits
3. AI flow
   - LLM request rate
   - LLM p95 latency
   - LLM failure rate
   - LLM token usage
4. Human handoff
   - Open handoff tasks
   - P0/P1 tasks
   - Oldest open task age
   - WebSocket operator connections
5. Notifications
   - Pending notification tasks
   - Oldest pending notification age
   - Sent/failed/cancelled counts
   - Eligibility block counts
6. Billing readiness
   - Stripe webhook received
   - Stripe signature failures
   - Checkout/order status counters

## Prometheus Scrape Plan

Initial targets:

- `api:8000/health` for blackbox-style HTTP health once blackbox exporter exists.
- `api:8000/metrics` after the application metrics endpoint is added.
- `postgres-exporter:9187/metrics` when database exporter is enabled.
- `redis-exporter:9121/metrics` when Redis exporter is enabled.
- `nginx-prometheus-exporter:9113/metrics` after Nginx status is configured.

This D7-1 package includes `monitoring/prometheus.yml` and `monitoring/docker-compose.monitoring.yml` as a deployment template. It does not modify the active `docker-compose.yml`.

## Implementation Phases

### Phase A: Design and dashboard assets

Completed by this task:

- Monitoring design document.
- Prometheus scrape config template.
- Grafana dashboard JSON template.
- Grafana datasource and dashboard provisioning templates.
- Optional monitoring compose file.

### Phase B: Application metrics endpoint

Next Codex-safe implementation task:

- Add `prometheus-client` to API dependencies.
- Add `/metrics` route.
- Instrument HTTP middleware.
- Add cheap database gauges for handoff and notification queues.
- Do not expose secrets or high-cardinality labels such as user IDs, message IDs, or raw trace IDs.

### Phase C: Runtime deployment

After Phase B:

- Start Prometheus and Grafana on localhost-only ports.
- Proxy Grafana behind an authenticated path or keep it SSH-only.
- Add retention limits.
- Add dashboard provisioning.

## Label Safety Rules

Never use these as labels:

- `user_id`
- `external_id`
- `conversation_id`
- `message_id`
- `notification_id`
- `trace_id`
- raw exception message
- prompt or response text

Allowed labels:

- route template, not raw URL
- HTTP method
- status code class or code
- channel
- notification type
- handoff priority
- queue status
- provider and model
- result enum

## D7-1 Acceptance Checklist

- [x] Six core ERIS metrics defined.
- [x] Dashboard layout defined.
- [x] Prometheus config template created.
- [x] Grafana dashboard JSON template created.
- [x] Grafana provisioning templates created.
- [x] Monitoring compose template created.
- [x] Active runtime left unchanged.
- [ ] `/metrics` endpoint implemented in a later task.
- [ ] Prometheus/Grafana deployed in a later task.
