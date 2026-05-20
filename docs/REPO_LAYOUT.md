# ERIS Repository Layout

Status: baseline
Owner: C-01
Last reviewed: 2026-05-20

This document is the repository layout baseline for ERIS. Product tasks should
refer to these paths when they mention the backend, admin dashboard, deployment,
or operational tooling.

## Canonical Layout

| Path | Purpose |
|---|---|
| `app/` | FastAPI backend, including HTTP APIs, Telegram entrypoints, WebSocket routes, and in-process workers |
| `app/main.py` | FastAPI application bootstrap and router registration |
| `app/api/` | API route modules, including `realtime.py` for WebSocket endpoints |
| `app/services/` | Business services: LLM orchestration, script matching, scoring, memory, safety, notifications, MTProto helpers |
| `app/core/` | Configuration and database wiring |
| `app/models/` | ORM model definitions when a task needs model-level structure |
| `app/schemas/` | Pydantic schemas and API contract objects |
| `admin/` | Next.js operations dashboard |
| `scripts/` | Database init, migrations, smoke checks, seed scripts, and operational helpers |
| `tests/` | Backend, service, contract, smoke, and regression tests |
| `docs/` | Product, architecture, runbook-adjacent, and acceptance documents |
| `ops/` | Operations specifications, including observability and logging rules |
| `monitoring/` | Prometheus, Grafana, Alertmanager, and related monitoring config |
| `fixtures/` | Synthetic test fixtures and smoke input data |
| `docker-compose.yml` | Local/production compose topology for API, PostgreSQL, and Redis |
| `AGENTS.md` | AI collaboration and execution rules |
| `RUNBOOK.md` | Deployment and incident operating notes |

## Technology Mapping

| Capability | Current implementation |
|---|---|
| Backend API | FastAPI in `app/`, container name `eris-api` |
| Database | PostgreSQL 16 with pgvector, service `postgres` |
| Cache / queue / short context | Redis 7, service `redis` |
| Realtime channel | WebSocket routes in `app/api/realtime.py` |
| Admin dashboard | Next.js app in `admin/` |
| Deployment | `docker compose` using `docker-compose.yml` |

## Legacy Plan Name Mapping

Older roadmap language may mention separate `gateway`, `ws`, `worker`, or
`dashboard` directories. The accepted ERIS MVP layout maps those names as:

| Legacy name | Accepted path |
|---|---|
| `gateway` | FastAPI routes under `app/api/` |
| `ws` | `app/api/realtime.py` and related WebSocket services |
| `worker` | In-process workers and schedulers under `app/services/` |
| `dashboard` | `admin/` |

Do not create top-level `gateway/`, `ws/`, `worker/`, or `dashboard/`
directories for MVP tasks unless a future architecture decision explicitly
changes this document.

## Deployment Boundary

All source changes happen in the local repository. GitHub is the transfer and
review layer. The production server only pulls merged code and restarts
containers; source files are not edited directly on the server.
