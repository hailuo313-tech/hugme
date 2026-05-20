# ERIS 仓库目录约定（C-01 验收依据）

> 本项目采用 **ERIS MVP 单体架构**，不再使用 execution-plan 初稿中的 `gateway/` / `ws/` / `worker/` / `dashboard/` 四目录 Node monorepo。  
> 任务分工里的「网关 / WS / Worker / 看板」均映射到下表路径。

## 顶层结构

| 路径 | 职责 | 对应原计划名称 |
|------|------|----------------|
| `app/` | FastAPI 后端（HTTP + Telegram + WebSocket + 进程内 Worker） | gateway + ws + worker |
| `app/api/` | 路由入口：`health`、`telegram`、`realtime`（WS）等 | gateway / ws |
| `app/services/` | 业务与后台任务：`embedding_worker`、`llm_orchestrator` 等 | worker |
| `app/core/` | 配置、数据库 | — |
| `admin/` | Next.js 运营看板 | dashboard |
| `docker-compose.yml` | 本地/生产：`api` + `postgres` + `redis` | 一键联调 |
| `monitoring/` | Prometheus / Grafana / Alertmanager | 可观测性 |
| `scripts/` | 迁移、E2E、部署脚本 | — |
| `docs/` | 设计与产品文档（含 `docs/product/`） | — |
| `AGENTS.md` | AI 协作与目录纪律 | C-01 必读 |
| `RUNBOOK.md` | 上线与排障 | — |

## C-01 验收清单

- [x] 存在 `app/`、`admin/`、`docker-compose.yml`、`AGENTS.md`
- [x] `AGENTS.md` §4 目录约定与本文一致
- [x] `GET /health` 由 `app/api/health.py` 提供（容器 `eris-api`）
- [x] WebSocket 由 `app/api/realtime.py` 提供（非独立 `ws/` 服务）
- [x] 异步任务在 `app/services/*_worker.py`（同进程 scheduler，非独立 `worker/` 容器）

## C-02 验收清单（CI 门禁）

- [x] `.github/workflows/pr-required-gates.yml` 对 `main` 的 PR 自动运行
- [x] **admin**：`npm run lint` + `npm run typecheck` + `npm run build`
- [x] **backend**：`ruff check` + `ruff format --check` + `mypy` + `pytest -q`
- [ ] GitHub 分支保护已勾选三项 required checks（需在仓库 Settings 手动开启）

## 本机 / 服务器路径

| 环境 | 路径 |
|------|------|
| 本机仓库 | `E:\eris` |
| 服务器 | `/opt/eris` |
| 静态产品页 | 本机 `docs/product/*.html` → 服务器 `/usr/share/nginx/html/` |

## 技术栈（H-01）

- API：**FastAPI**（非 Fastify）
- DB：PostgreSQL + pgvector
- 缓存/队列：Redis
- 看板：`admin/`（Next.js）
- 部署：Docker Compose + Nginx 反代
