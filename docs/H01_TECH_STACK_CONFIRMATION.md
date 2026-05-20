# H-01 Technology Stack And Deployment Confirmation

Status: confirmed
Task: H-01 - 确认技术选型（FastAPI/PostgreSQL/Redis/WS）与部署环境
Confirmed on: 2026-05-20

## Written Confirmation

ERIS phase 01 infrastructure is confirmed to use the following stack:

| Area | Confirmed choice |
|---|---|
| Backend API | FastAPI |
| Primary database | PostgreSQL with pgvector |
| Cache / queue / short-term context | Redis |
| Realtime transport | WebSocket |
| Admin dashboard | Next.js under `admin/` |
| Deployment unit | Docker Compose |
| API container | `eris-api` |
| Database service | `postgres` |
| Redis service | `redis` |

The deployment environment is the current ERIS Docker Compose environment. The
repository root contains `docker-compose.yml`, which defines `postgres`,
`redis`, and `api` services. The API service builds from `app/Dockerfile` and
serves the FastAPI application.

## Repository Layout Consistency

This confirmation is aligned with `docs/REPO_LAYOUT.md`:

- Backend code lives in `app/`.
- API routes live in `app/api/`.
- WebSocket routes live in `app/api/realtime.py`.
- Business services live in `app/services/`.
- Configuration and database wiring live in `app/core/`.
- Admin dashboard code lives in `admin/`.
- Database init and migration helpers live in `scripts/`.
- Deployment topology is defined by `docker-compose.yml`.

Older plan names such as `gateway`, `ws`, `worker`, and `dashboard` are mapped
to the accepted `app/` and `admin/` layout described in `docs/REPO_LAYOUT.md`.
They are not separate top-level MVP directories.

## Operating Rule

Source code changes happen only in the local repository and are reviewed through
GitHub PRs. The production server is used for pulling merged code and restarting
containers; source files are not edited directly on the server.

## Acceptance

- [x] Written confirmation exists.
- [x] FastAPI / PostgreSQL / Redis / WebSocket are confirmed.
- [x] Deployment environment is documented.
- [x] The confirmation is consistent with `docs/REPO_LAYOUT.md`.
