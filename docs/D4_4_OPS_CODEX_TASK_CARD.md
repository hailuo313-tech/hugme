# D4-4-OPS Codex 验收任务卡：生产启用 SCORE_WORKER + handoff 阈值 smoke

## 背景

D4-4 的代码已在仓库：`profile_score_worker` 周期性更新 `user_profiles.initiation_score`
与 `trigger_threshold`；`policy_service` 在 `POLICY_SERVICE_ENABLED=1` 时根据
`initiation_score >= trigger_threshold` 创建 `handoff_tasks`（`trigger_reason='policy:initiation_hot'`）。

当前未闭环的是**生产显式启用**与**端到端 smoke 证明**。

## 2026-05-16 首轮验收结果

首轮 OPS smoke 结论：**部分通过，未全绿**。

- 通过：手动 `run_profile_score_tick` 成功，smoke 用户 `initiation_score=0 → 100`，
  `trigger_threshold=65 → 58.25`，`over_threshold=true`，日志出现
  `profile_score_worker.tick.done`。
- 阻断：生产 `docker-compose.yml` 未把 `SCORE_WORKER_*` / `POLICY_*` 从 `.env`
  透传进 `eris-api`，容器内表现为 `NO_SCORE_OR_POLICY_ENV_IN_CONTAINER` 与
  `profile_score.scheduler.disabled`。
- 阻断：生产 `main @ 4af4e2a` 未包含 `POLICY_SERVICE_ENABLED` /
  `maybe_create_policy_handoff` / `policy:initiation_hot`，因此 handoff 阈值 smoke
  查询 `0 rows`。

重跑本任务前必须先合入修复 PR：compose 透传 D4-4/POL-01 环境变量，并确保
Policy Service 逻辑已部署到生产镜像。

## Owner

- 验收执行：Codex
- 产物回填：在 PR/验收评论里贴命令输出摘要、SQL 结果、日志关键行

## 前置条件

- 服务器路径：`/opt/eris`
- 容器名按当前部署：`eris-api`、`eris-postgres`
- 需要能编辑宿主 `.env` 并重启 API 容器
- 不使用真实用户做 smoke；只创建 `external_id` 带 `d4_4_ops_smoke_` 前缀的测试用户

## 生产开关

在 `/opt/eris/.env` 确认或追加：

```bash
SCORE_WORKER_ENABLED=1
SCORE_WORKER_POLL_SECONDS=120
SCORE_WORKER_SCHEDULER_MAX_INSTANCES=1
SCORE_INITIATION_LOOKBACK_DAYS=7
SCORE_INITIATION_CAP_MESSAGES=40
SCORE_PROFILE_MIN_UPDATE_DELTA=0.05
TRIGGER_THRESHOLD_BASE=65
TRIGGER_THRESHOLD_PIVOT=35
TRIGGER_THRESHOLD_K=0.15
TRIGGER_THRESHOLD_FLOOR=50
TRIGGER_THRESHOLD_CEIL=82
POLICY_SERVICE_ENABLED=1
POLICY_RISK_SCORE_THRESHOLD=75
POLICY_LONELINESS_THRESHOLD=82
POLICY_VIP_LEVEL_THRESHOLD=1
POLICY_HANDOFF_COUNT_THRESHOLD=3
```

重启 API：

```bash
cd /opt/eris
docker compose up -d api
docker inspect eris-api --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep -E 'SCORE_WORKER|SCORE_INITIATION|TRIGGER_THRESHOLD|POLICY_SERVICE|POLICY_.*THRESHOLD'
```

通过标准：容器内能看到 `SCORE_WORKER_ENABLED=1` 与 `POLICY_SERVICE_ENABLED=1`。

## Smoke A：worker tick 更新画像分

创建一组测试数据：

```bash
cd /opt/eris
POSTGRES_USER=${POSTGRES_USER:-eris}
POSTGRES_DB=${POSTGRES_DB:-eris}
SMOKE_TAG="d4_4_ops_smoke_$(date +%Y%m%d%H%M%S)"

docker exec eris-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v tag="$SMOKE_TAG" -c "
WITH u AS (
  INSERT INTO users (channel, external_id, nickname, status)
  VALUES ('ops_smoke', :'tag', 'D4-4 OPS Smoke', 'active')
  RETURNING id
),
c AS (
  INSERT INTO conversations (user_id, channel, state)
  SELECT id, 'ops_smoke', 'AI_ACTIVE' FROM u
  RETURNING id, user_id
),
p AS (
  INSERT INTO user_profiles (user_id, loneliness_score, initiation_score, trigger_threshold)
  SELECT user_id, 100, 0, 65 FROM c
  RETURNING user_id
)
INSERT INTO messages (conversation_id, sender_type, sender_id, content, content_type, created_at)
SELECT c.id, 'user', c.user_id::text, 'smoke msg ' || gs::text, 'text', NOW()
FROM c, generate_series(1, 40) AS gs;
"
```

手动触发一次 worker tick（不用等 scheduler 周期）：

```bash
docker exec -e SMOKE_TAG="$SMOKE_TAG" eris-api python - <<'PY'
import asyncio
from services.profile_score_worker import run_profile_score_tick

async def main():
    out = await run_profile_score_tick("d4-4-ops-smoke")
    print(out)

asyncio.run(main())
PY
```

检查画像分：

```bash
docker exec eris-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v tag="$SMOKE_TAG" -c "
SELECT u.external_id, up.initiation_score, up.trigger_threshold, up.score_updated_at
FROM users u
JOIN user_profiles up ON up.user_id = u.id
WHERE u.external_id = :'tag';
"
```

通过标准：

- `run_profile_score_tick` 输出 `skipped=False`
- `profiles_scanned >= 1`
- 测试用户 `initiation_score` 约为 `100`
- `trigger_threshold` 被更新到 50–82 区间内，且 `score_updated_at IS NOT NULL`

## Smoke B：handoff 阈值触发任务

在 API 容器里直接调用 `maybe_create_policy_handoff`，验证 `initiation_hot` 规则能创建任务：

```bash
docker exec eris-api python - <<'PY'
import asyncio
import os
from sqlalchemy import text
from core.database import AsyncSessionLocal
from services.policy_service import maybe_create_policy_handoff

tag = os.environ.get("SMOKE_TAG")
if not tag:
    raise SystemExit("missing SMOKE_TAG env; run with docker exec -e SMOKE_TAG=...")

async def main():
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text("""
            SELECT u.id::text AS user_id, c.id::text AS conversation_id,
                   up.risk_score, up.loneliness_score, up.initiation_score,
                   up.trigger_threshold, up.vip_level
            FROM users u
            JOIN conversations c ON c.user_id = u.id
            JOIN user_profiles up ON up.user_id = u.id
            WHERE u.external_id = :tag
            ORDER BY c.created_at DESC
            LIMIT 1
        """), {"tag": tag})).fetchone()
        if row is None:
            raise SystemExit(f"smoke user not found: {tag}")
        m = dict(row._mapping)
        task_id = await maybe_create_policy_handoff(
            db,
            user_id=m["user_id"],
            conversation_id=m["conversation_id"],
            user_text="D4-4 OPS smoke threshold check",
            profile_row=m,
            trace_id="d4-4-ops-smoke",
        )
        print({"task_id": task_id, "profile": m})

asyncio.run(main())
PY
```

如果 shell 不支持把 heredoc stdin 直接传给 `docker exec`，可把脚本临时写入容器或将
`SMOKE_TAG` 写死为本次生成的 tag 后执行。

检查 handoff：

```bash
docker exec eris-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v tag="$SMOKE_TAG" -c "
SELECT ht.id, ht.priority, ht.status, ht.trigger_reason, ht.created_at
FROM handoff_tasks ht
JOIN users u ON u.id = ht.user_id
WHERE u.external_id = :'tag'
ORDER BY ht.created_at DESC;
"
```

通过标准：

- `maybe_create_policy_handoff` 返回非空 `task_id`
- `handoff_tasks.trigger_reason = 'policy:initiation_hot'`
- `priority = 'P3'`
- `status = 'pending'`
- 再跑一次相同 policy 调用不会创建第二张未关闭 handoff（open-task 门控生效）

## 日志证据

```bash
docker logs --since=10m eris-api 2>&1 | grep -E \
  'profile_score_worker.tick.done|profile_score.scheduler.started|orchestrator.policy.handoff_created|policy.handoff.created'
```

通过标准：至少看到 `profile_score_worker.tick.done`；若 smoke 走真实对话主链路，则应看到 `orchestrator.policy.handoff_created`。

## 清理测试数据

验收截图/输出保存后清理：

```bash
docker exec eris-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v tag="$SMOKE_TAG" -c "
DELETE FROM handoff_tasks
WHERE user_id IN (SELECT id FROM users WHERE external_id = :'tag');

DELETE FROM users
WHERE external_id = :'tag';
"
```

`user_profiles`、`conversations`、`messages` 会随外键/或显式清理策略处理；若当前 schema 未级联所有表，按外键报错顺序补删对应测试行。

## 回滚条件

出现以下任一情况，回滚开关并重启 API：

- `profile_score_worker.tick.failed` 持续出现
- handoff 队列异常暴涨或重复任务门控失效
- API P95 / 错误率明显恶化

回滚：

```bash
cd /opt/eris
# 将 .env 中 SCORE_WORKER_ENABLED=0；必要时 POLICY_SERVICE_ENABLED=0
docker compose up -d api
```

## 验收结论模板

```text
D4-4-OPS 验收结论：PASS / FAIL

环境：
- host:
- commit/tag:
- SCORE_WORKER_ENABLED:
- POLICY_SERVICE_ENABLED:

Smoke A:
- worker output:
- initiation_score / trigger_threshold:
- log line:

Smoke B:
- task_id:
- trigger_reason:
- duplicate gate result:

清理：
- smoke tag:
- cleanup result:

风险/后续：
```
