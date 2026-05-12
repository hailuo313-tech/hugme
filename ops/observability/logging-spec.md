# ERIS Logging Specification

Date: 2026-05-12
Owner: Codex AI
Scope: D1-4 observability/logging
Status: active spec for new work; existing mixed-format logs should be migrated opportunistically

## Goals

ERIS logs must make it possible to follow one user request across API middleware, Telegram ingress, message persistence, LLM calls, handoff, WebSocket updates, notifications, and billing without exposing secrets or sensitive user content.

This spec standardizes:

- JSON log output.
- `trace_id` propagation.
- Event naming.
- Required fields.
- Sensitive-data redaction rules.
- Minimum operational queries for beta debugging.

## Current Implementation

FastAPI configures Loguru with `serialize=True`, so logs are emitted as JSON to stdout.

The HTTP middleware in `app/main.py` currently:

- reads `x-trace-id` or `x-request-id`;
- generates a UUID when no trace header exists;
- stores the value at `request.state.trace_id`;
- adds `X-Trace-Id` to every HTTP response;
- logs `http.request.start`, `http.request.complete`, and `http.request.error`.

Some older code still writes messages like `[trace_id] event details` instead of binding structured fields. New code should use `logger.bind(...)` and a stable event name.

## Trace ID Rules

Every inbound unit of work must have a `trace_id`.

Sources:

1. Use `X-Trace-Id` if provided.
2. Else use `X-Request-Id` if provided.
3. Else generate a UUID.

Propagation:

- HTTP handlers read `request.state.trace_id`.
- Internal service calls receive `trace_id` as an explicit argument when practical.
- WebSocket clients may pass `trace_id` as a query param for debugging.
- Outbound HTTP calls should send `X-Trace-Id` where supported.
- Responses should expose `X-Trace-Id`.

Never use `trace_id` as a Prometheus label.

## Log Format

All new logs should use this shape:

```python
logger.bind(
    trace_id=trace_id,
    component="messages",
    user_id_hash=user_id_hash,
    conversation_id_hash=conversation_id_hash,
).info("message.inbound.persisted")
```

Required fields when available:

| Field | Required | Notes |
|---|---:|---|
| `trace_id` | yes | Request or job correlation ID |
| `component` | yes | `api`, `telegram`, `messages`, `llm`, `handoff`, `notifications`, `payments`, `ws` |
| `event` | yes | Loguru message string, dot-delimited |
| `level` | yes | Provided by logger |
| `method` | HTTP only | HTTP method |
| `path` | HTTP only | Route path; prefer template over raw path when available |
| `status_code` | HTTP complete | Response status |
| `duration_ms` | timed operations | Integer or rounded float |
| `result` | important actions | `success`, `failed`, `blocked`, `duplicate`, `timeout`, `fallback` |

Allowed identifiers:

- `channel`
- `message_type`
- `notification_type`
- `handoff_priority`
- `operator_id` when it is not personally sensitive
- hashed or internal-only IDs when needed for debugging

Avoid raw IDs in normal logs unless the value is already operationally public and not user-sensitive.

## Event Naming

Use lower-case dot-delimited event names:

`<domain>.<object_or_action>.<state>`

Good examples:

- `http.request.start`
- `http.request.complete`
- `message.inbound.received`
- `message.inbound.persisted`
- `message.inbound.idempotent_hit`
- `telegram.webhook.received`
- `telegram.webhook.duplicate`
- `llm.call.start`
- `llm.call.response`
- `llm.fallback.start`
- `handoff.task.created`
- `handoff.task.claimed`
- `ws.operator.connected`
- `ws.operator.tasks_pushed`
- `notification.task.scheduled`
- `notification.task.cancelled`
- `stripe.webhook.received`
- `stripe.webhook.signature_failed`

Avoid:

- free-form sentences as event names;
- event names containing user text;
- event names containing IDs;
- mixed naming like `tg.webhook.complete` in new code unless preserving an existing event for compatibility.

## Severity Guidelines

| Level | Use for |
|---|---|
| `DEBUG` | Local-only details; disabled in production unless troubleshooting |
| `INFO` | Normal lifecycle events and successful state transitions |
| `WARNING` | Recoverable failures, fallback, rate limit, invalid user input, duplicate webhook |
| `ERROR` | Failed dependency or operation that affects the request/job |
| `EXCEPTION` | Unexpected exception with stack trace |

## Sensitive Data Rules

Never log:

- API keys, bot tokens, Stripe keys, webhook secrets, DB passwords, Redis passwords.
- User message content or AI response text.
- Payment card, bank, invoice, or receipt details.
- Raw Telegram token, Stripe signature, authorization header, cookies.
- Full email, phone, or external user IDs unless explicitly hashed/redacted.

Recommended redaction helpers for future implementation:

- `redact_secret(value)` -> first 4 chars + `...` + last 4 chars only for admin diagnostics.
- `hash_id(value)` -> stable HMAC or salted SHA-256 digest, not plain SHA over public IDs.
- `safe_exception(exc)` -> exception class + safe category, not raw provider payload.

## Domain-Specific Requirements

### HTTP/API

Must log:

- `http.request.start`
- `http.request.complete`
- `http.request.error`

Fields:

- `trace_id`
- `method`
- `path`
- `status_code`
- `duration_ms`
- `client_ip` only if needed; consider hashing or removing before public log export.

### Telegram

Must log:

- webhook received
- invalid JSON
- duplicate update
- inbound persisted
- bot reply sent/failed

Do not log message text. Use `update_id`, `channel`, `message_type`, and safe result fields.

### Messages

Must log:

- inbound received
- idempotency hit
- user found/created
- conversation found/created
- message persisted
- Redis context push success/failure
- rate-limit block

Do not log user content.

### LLM

Must log:

- provider/model request start
- provider/model response
- timeout
- fallback start
- fallback failure

Fields:

- `provider`
- `model`
- `duration_ms`
- `status_code` if HTTP based
- `result`
- token/cost counts only if they do not expose prompt text

Do not log prompts or completions.

### Handoff/WebSocket

Must log:

- handoff task create/claim/close
- WebSocket connect/disconnect
- task snapshot pushed
- operator ack

Fields:

- `operator_id`
- `task_count`
- `priority`
- `result`

Avoid sending user-sensitive task detail into logs.

### Notifications

Must log:

- task scheduled
- eligibility blocked
- dedupe blocked
- task sent/failed/cancelled

Fields:

- `notification_type`
- `channel`
- `result`
- `failure_category`

Do not log notification body.

### Stripe/Billing

Must log:

- webhook received
- signature verification success/failure
- event type
- order/payment state transition

Do not log:

- Stripe signature header
- full event payload
- customer payment details
- secret keys

## Migration Notes

Existing logs that look like this:

```python
logger.info(f"[{trace_id}] llm.call.start model={model}")
```

Should migrate to:

```python
logger.bind(
    trace_id=trace_id,
    component="llm",
    model=model,
).info("llm.call.start")
```

Migrations should be done incrementally when touching the relevant module. Do not refactor unrelated modules solely for log style unless the task is explicitly about logging cleanup.

## Operational Queries

Follow one request:

```bash
docker logs eris-api --since 30m | grep '<trace_id>'
```

Find recent API errors:

```bash
docker logs eris-api --since 30m | grep 'http.request.error'
```

Find Telegram webhook issues:

```bash
docker logs eris-api --since 2h | grep -E 'telegram|tg.webhook|tg.send'
```

Find LLM fallback/failure:

```bash
docker logs eris-api --since 2h | grep -E 'llm.*fallback|llm.*error|OPENROUTER'
```

Find notification scheduling:

```bash
docker logs eris-api --since 2h | grep 'notification.task'
```

## Acceptance Checklist

- [x] JSON logging contract documented.
- [x] Trace ID propagation documented.
- [x] Required fields documented.
- [x] Sensitive data redaction rules documented.
- [x] Event naming convention documented.
- [x] Migration path for mixed-format logs documented.
- [x] Ops query examples documented.

