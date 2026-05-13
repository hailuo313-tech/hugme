# Changelog

## v0.1.0 - 2026-05-13

ERIS MVP v0.1.0 closes the D0-D7 launch runway: production infrastructure,
Telegram entry, AI conversation, onboarding, admin operations, handoff,
payments, reactivation, monitoring, E2E smoke, and beta-launch operations.

### D0-D1: Foundation and Telegram Entry

- Imported the production server codebase into Git so `/opt/eris` can be
  deployed from source control instead of hand edits.
- Preserved the FastAPI, PostgreSQL, Redis, Docker Compose, and init SQL
  baseline from the initial production skeleton.
- Kept Telegram webhook, inbound message persistence, Redis short context, and
  Telegram idempotency behavior from the pre-PR baseline.

### D2: AI Conversation and Onboarding

- [#1](https://github.com/hailuo313-tech/hugme/pull/1) replaced Telegram echo
  with the LLM orchestrator and structured logging.
- [#2](https://github.com/hailuo313-tech/hugme/pull/2) made the orchestrator
  read Redis short-term context and added the conversation reply endpoint.
- The baseline includes the five-step onboarding flow, default Aria assignment,
  and GDPR consent timestamp at onboarding completion.

### D5: Admin, Handoff, and Realtime Operations

- The baseline includes operator JWT login and the Next.js admin shell.
- [#3](https://github.com/hailuo313-tech/hugme/pull/3) added the WebSocket
  operator task protocol with true delta updates.
- [#9](https://github.com/hailuo313-tech/hugme/pull/9) added admin
  conversation list and detail views.
- [#10](https://github.com/hailuo313-tech/hugme/pull/10) fixed JSON-safe
  serialization for admin conversation rows.
- [#11](https://github.com/hailuo313-tech/hugme/pull/11) fixed nullable
  asyncpg bind parameters in the admin conversation filters.

### D6: Payments and Silent Reactivation

- [#4](https://github.com/hailuo313-tech/hugme/pull/4) added the silent
  reactivation evaluator, runner, admin trigger, and tests.
- [#5](https://github.com/hailuo313-tech/hugme/pull/5) passed runtime feature
  flags into the API container.
- [#7](https://github.com/hailuo313-tech/hugme/pull/7) added the scheduled
  silent reactivation scan.
- [#8](https://github.com/hailuo313-tech/hugme/pull/8) added Stripe webhook
  verification, idempotency, async ACK, and event processing.
- [#13](https://github.com/hailuo313-tech/hugme/pull/13) added Stripe Checkout
  order creation and order status lookup.

### D7: Monitoring, Release Readiness, and E2E

- [#6](https://github.com/hailuo313-tech/hugme/pull/6) removed the obsolete
  Docker Compose top-level `version` key.
- [#12](https://github.com/hailuo313-tech/hugme/pull/12) made the monitoring
  stack runnable and fixed the Grafana port clash.
- [#14](https://github.com/hailuo313-tech/hugme/pull/14) documented the
  2026-05-13 ops health check, container status, Prometheus state, and admin
  password rotation.
- [#15](https://github.com/hailuo313-tech/hugme/pull/15) added the D7-3 E2E
  smoke script for Telegram registration, onboarding, 50-turn conversation,
  handoff, and Stripe Checkout creation.
- Added `scripts/backup.sh` for daily PostgreSQL + Redis backups with 7-day
  retention.
- Added `docs/BETA_CHECKLIST.md` so one operator can invite the first beta user,
  watch day-one metrics, and roll back safely.

### Release Validation

- `https://hugme2.com/health/detail` returned `{"api":"ok","db":"ok","redis":"ok"}`
  during the D7-3 server run.
- D7-3 E2E server smoke completed with `PASS=97 FAIL=0 RESULT=PASS`.
- v0.1.0 backup procedure creates a tarball under `/opt/eris/backups/` containing
  PostgreSQL custom/plain dumps, Redis RDB, and git metadata.
