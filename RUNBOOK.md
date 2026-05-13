# ERIS MVP Runbook v1

Last updated: 2026-05-12
Host: `67.216.204.137`
Domain: `hugme2.com`
Project root: `/opt/eris`

## Current System

Services:

```text
eris-api        FastAPI app, local port 127.0.0.1:8000
eris-postgres   PostgreSQL + pgvector, local port 127.0.0.1:5432
eris-redis      Redis, local port 127.0.0.1:6379
nginx           public HTTP/HTTPS reverse proxy
```

Public endpoints:

```text
https://hugme2.com/health
https://hugme2.com/health/detail
https://hugme2.com/roadmap
wss://hugme2.com/ws/operators/tasks?operator_id=<operator-id>
```

SSH:

```bash
ssh -i C:\Users\13267\.ssh\eris_67.216.204.137 -p 2222 root@67.216.204.137
```

## Health Checks

From any machine:

```bash
curl -i https://hugme2.com/health
curl -i https://hugme2.com/health/detail
```

On server:

```bash
cd /opt/eris
docker ps
docker compose ps
curl -i http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/health/detail
```

Expected:

```text
/health        200 {"status":"ok","service":"ERIS API","version":"0.1.0"}
/health/detail 200 {"api":"ok","db":"ok","redis":"ok"}
```

## Logs

API logs:

```bash
docker logs --tail 200 eris-api
docker logs -f eris-api
```

Trace one request:

```bash
curl -H 'X-Trace-Id: manual-check-001' https://hugme2.com/health
docker logs --tail 200 eris-api | grep manual-check-001
```

Nginx logs:

```bash
tail -100 /var/log/nginx/eris.access.log
tail -100 /var/log/nginx/eris.error.log
tail -100 /var/log/nginx/error.log
```

Certbot logs:

```bash
tail -100 /var/log/letsencrypt/letsencrypt.log
```

## Memory Writer: 三阶段记忆写入 (D3-3)

**核心**：`app/services/memory_writer.py` 在用户消息持久化之后被
`asyncio.create_task(...)` 异步触发，自带 DB session，**绝不阻塞**用户回复。

```text
Phase 1  规则预过滤  ─ too_short / acknowledgement / emoji-only / 24h dedup
Phase 2  LLM 评分    ─ JSON 输出 {is_memory_worthy, memory_type, content,
                                  importance_score, confidence, emotion_tags}
Phase 3  持久化      ─ INSERT INTO memories (embedding=NULL，D3-4 异步补)
```

**接入点**：
- `app/api/telegram.py` — 用户消息持久化 + 上下文 push 后立即触发；onboarding
  期间 `is_onboarding=True`，writer 直接跳过（onboarding 数据走 user_profiles）。
- `app/api/messages.py` — `/api/v1/messages/inbound` 同样触发，默认 onboarding=False。

**环境变量**（`.env`）：

```bash
MEMORY_WRITE_ENABLED=true                  # 总开关；false 时 writer noop
LLM_MEMORY_MODEL=openai/gpt-4o-mini        # 评分用模型；留空走主备路由
MEMORY_IMPORTANCE_THRESHOLD=5              # 评分 ≥ 此值才入库
```

**日志事件**（均带 `trace_id` + `component=memory_writer`）：

```text
memory.write.start
memory.write.prefilter_skip       reason=too_short|acknowledgement|emoji_or_punct_only|duplicate_24h|onboarding|disabled_by_flag|empty
memory.write.llm.start            model=...
memory.write.llm.failed           reason / error_type
memory.write.llm.scored           importance / memory_type / confidence / duration_ms
memory.write.below_threshold      score / threshold
memory.write.persisted            memory_id / importance
memory.write.persist_failed       error_type
```

**Smoke**（服务器上跑）：

```bash
# 1) 模块可正确导入（拦 SyntaxError 类问题）
docker exec eris-api python -m py_compile app/services/memory_writer.py && echo "OK"

# 2) 真发一条有营养的 TG 消息后，看日志是否走完三阶段
docker logs --tail 200 eris-api | grep -E "memory\.write\.(start|scored|persisted)"

# 3) DB 校验
docker exec eris-postgres psql -U eris -d eris -c \
  "SELECT id, memory_type, importance_score, content, created_at FROM memories \
   ORDER BY created_at DESC LIMIT 5;"
```

**预期**：寒暄/嗯哼/表情包等不入库；身份事实/偏好/关系/创伤等 importance≥5 才入库。

## LLM Orchestrator: 10 层 Prompt 结构 (D3-2)

**核心**：`app/services/prompt_builder.py` 把 system content 拆成 10 个层，
每层一个 `## ===== Lx_NAME =====` 标签，便于线上 grep。

```text
L1_SAFETY            硬红线（自伤 / 未成年 / 越狱抗性）
L2_IDENTITY          "我是 Aria"
L3_CHARACTER         characters 表 → 人格 6 维 band（low/mid/high）
L4_RELATIONSHIP      user_profiles.relationship_stage + vip_level
L5_USER_PROFILE      chat_style / interests / forbidden_topics / nickname
L6_MEMORY            D4-1 接入后填实；D3-2 是占位
L7_CONVERSATION_STATE loneliness_score 分段（low/mid/high/critical）
L8_RECENT_CONTEXT    走 messages 数组，不在 system
L9_FORMAT            character 决定的 reply_length / tone / emoji 频率
L10_ANCHOR           末层锚点：再次提醒"先共情、L1 硬红线、你是 Aria"
```

**调用入口**：`generate_reply(..., db=AsyncSession)` —— 提供 db 时自动查
`characters`（经 `conversations.character_id` LEFT JOIN）+ `user_profiles`。
任意 db 查询失败被吞，对应层走"未知/默认"降级；不阻塞回复。

**日志**：`orchestrator.prompt.assembled` 会带：
- `layers`: 10 层名称
- `layers_with_data`: 实际有内容的层（用于排查"为什么 L3 是默认人格"）
- `system_chars` / `estimated_tokens`：粗估，告警阈值用
- `has_character` / `has_profile`：bool

**Smoke**：

```bash
docker exec eris-api python -c "
from services.prompt_builder import DEFAULT_SYSTEM_PROMPT, LAYER_ORDER
for label in LAYER_ORDER:
    if label == 'L8_RECENT_CONTEXT':
        continue
    assert '## ===== ' + label + ' =====' in DEFAULT_SYSTEM_PROMPT
print('OK: 9 system layers all present')
"
```

发一条 Telegram 消息后，看 `docker logs eris-api | grep prompt.assembled` 应有一行带 `layers_with_data=[...]`。

## Admin: 会话列表 / 详情 (D5-2)

**前端**：Next.js 应用 `admin/`，`basePath=/admin`，构建后由 Nginx 静态托管；运行时通过
`next.config.js` 的 rewrite 把 `/admin/api/:path*` 反代到 `http://127.0.0.1:8000/api/:path*`。

**后端接口（均要 operator JWT）**：

- `GET /api/v1/admin/conversations` — 会话列表
  - 查询参数：`page` (≥1, 默认 1)、`page_size` (1–100, 默认 20)
  - 过滤：`state` ∈ {`AI_ACTIVE`, `WAITING_OPERATOR`, `HUMAN_LOCKED`, `CLOSED`}（白名单，非法 → 400）
  - 过滤：`channel` ∈ {`telegram`, `whatsapp`, `web`, `discord`}（白名单，非法 → 400）
  - 模糊搜索：`search` —— 对 `users.nickname` / `users.external_id` 做 `ILIKE %q%`
  - 排序：`COALESCE(last_message_at, created_at) DESC`
  - 返回：`{items: [...], total, page, page_size}`
- `GET /api/v1/admin/conversations/{conversation_id}` — 会话详情
  - 校验 UUID 格式；非法 → 400
  - 不存在 → 404
  - 返回 `{conversation: {...meta + 用户画像 + 角色}, messages: [...最近 50 条按时间倒序]}`

**Smoke**（在服务器上跑，先拿一个 operator token，再调列表）：

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/admin/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<your-pw>"}' | python -c "import sys,json;print(json.load(sys.stdin)['token'])")

curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/v1/admin/conversations?page=1&page_size=5" | python -m json.tool

curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/v1/admin/conversations?state=AI_ACTIVE&search=tg" | python -m json.tool

# 401 反向验证
curl -i http://127.0.0.1:8000/api/v1/admin/conversations
```

**期望**：

- 无 token → `401`
- 列表 → `200` + JSON `{items: [...], total: N, page: 1, page_size: 5}`
- `state=BANANA` → `400`
- 详情命中 → `200` + `{conversation, messages}`；不存在的 UUID → `404`

**前端部署**：

```bash
cd /opt/eris/admin
npm ci
npm run build
docker compose restart admin   # 若 admin 在 compose 中跑；否则按现有部署方式重启
```

## Stripe webhook (D6-2)

**Required env**（宿主 `/opt/eris/.env`；compose `api.environment` 已透传）：

- `STRIPE_SECRET_KEY` — D6-1 创建 Checkout Session 用
- `STRIPE_WEBHOOK_SECRET` — D6-2 验签用；**缺失会让 webhook 返回 400 signature_failed，DB 不写**
- `STRIPE_SUCCESS_URL` / `STRIPE_CANCEL_URL` — Checkout 跳转，默认 `https://hugme2.com/payment/{success,cancel}`

**接口**：`POST /api/v1/webhooks/stripe`

- 同步阶段（毫秒级）：验签 → 抢占 `stripe_webhook_events.event_id`（ON CONFLICT DO NOTHING）→ 返回 200 `queued`/`duplicate`。
- 后台阶段：`checkout.session.completed` → `orders.status='paid' + paid_at=NOW()` → `users.vip_level += 1`；其它事件 `result='ignored'`。
- 完成后回写 `stripe_webhook_events.result` (`processed`/`ignored`/`failed`) + `handled_at`。

**首次部署需要**：新表 `stripe_webhook_events`。`init.sql` 已声明，但 docker volume 上的 PG 不会重跑该脚本，需手动建表（一次性）：

```bash
docker exec eris-postgres psql -U eris -d eris -c "
CREATE TABLE IF NOT EXISTS stripe_webhook_events (
    event_id VARCHAR(64) PRIMARY KEY,
    event_type VARCHAR(80) NOT NULL,
    payload JSONB NOT NULL,
    result VARCHAR(20) DEFAULT 'received',
    error TEXT,
    received_at TIMESTAMP DEFAULT NOW(),
    handled_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_stripe_webhook_events_type_received
    ON stripe_webhook_events(event_type, received_at DESC);
"
```

**Stripe Dashboard 配置**（手动）：在 Stripe Test 后台 Webhooks → Add endpoint → `https://hugme2.com/api/v1/webhooks/stripe`，订阅事件至少：`checkout.session.completed`；签名密钥贴到 `.env` 的 `STRIPE_WEBHOOK_SECRET`。

**Smoke**（在服务器上用 Stripe CLI 转发 + 4242 测试卡走一遍 Checkout）：

```bash
docker logs --since=5m eris-api 2>&1 | grep -E 'stripe_webhook|payments\.'
docker exec eris-postgres psql -U eris -d eris -c "
SELECT event_id, event_type, result, handled_at FROM stripe_webhook_events ORDER BY received_at DESC LIMIT 5;"
docker exec eris-postgres psql -U eris -d eris -c "
SELECT id, status, paid_at, provider_order_id FROM orders ORDER BY created_at DESC LIMIT 5;"
```

期望：events 表有该 `evt_*` 行 `result='processed'`；对应 `orders.status='paid'`、`users.vip_level` +1。

## Silent reactivation (D6-3)

**Flags**（宿主 `/opt/eris/.env`；`docker-compose.yml` 的 `api.environment` 必须显式透传，容器内才读得到）：

- `SILENT_REACTIVATION_ENABLED=1` —— 打开后才会查库 / 写 `notification_tasks`；`0` 时 admin 接口与定时任务均 short-circuit。
- `SILENT_REACTIVATION_CRON` —— 可选；crontab 五段，**UTC**（默认 `0 2 * * *` = 每天 UTC 02:00）。仅在 `SILENT_REACTIVATION_ENABLED=1` 时注册 APScheduler job。

**手动 smoke**（在服务器上，`127.0.0.1:8000` 为 api 容器映射）：

1. 登录拿 JWT —— 路径是 **`POST /api/v1/admin/login`**（不是 `/auth/login`），body 用 **`username` + `password`**（`operators` 表；默认 seed 账号 **`admin`**）。

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/admin/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"YOUR_PASSWORD"}' \
  | docker exec -i eris-api python -c "import sys,json; print(json.load(sys.stdin)['token'])")
```

2. 触发一次扫描：

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/admin/silent-reactivation/run \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{}' | docker exec -i eris-api python -m json.tool
```

期望 JSON 含 `"enabled": true`（flag 打开时）；`docker logs eris-api` 出现 `silent_reactivation.scan.start` / `candidates_loaded` / `scan.complete`。

**定时调度**：合并含 scheduler 的代码后 `docker compose up -d --build --force-recreate api`（`requirements.txt` 有变更需重建镜像）。启动日志应含 `silent_reactivation.scheduler.started`（仅 `SILENT_REACTIVATION_ENABLED=1` 时）。多 worker 时同一时刻只会有一个实例抢到 `pg_try_advisory_lock`，其余打 `silent_reactivation.scheduler.skip_no_lock`。

## Restart Procedures

Restart API only:

```bash
cd /opt/eris
docker compose up -d --build api
```

Restart all app containers:

```bash
cd /opt/eris
docker compose up -d --build
```

Restart Nginx:

```bash
nginx -t
systemctl reload nginx
```

Restart Redis/Postgres only when needed:

```bash
cd /opt/eris
docker compose restart redis
docker compose restart postgres
```

## Environment Variables

Server env file:

```text
/opt/eris/.env
```

Required keys:

```text
POSTGRES_DB
POSTGRES_USER
POSTGRES_PASSWORD
REDIS_PASSWORD
SECRET_KEY
OPENROUTER_API_KEY
TELEGRAM_BOT_TOKEN
ENV
STRIPE_PUBLISHABLE_KEY
STRIPE_SECRET_KEY
STRIPE_WEBHOOK_SECRET
```

Never paste real values into chat.

Safe check for variable names:

```bash
cd /opt/eris
nl -ba .env | sed -E 's/(=).+/=***REDACTED***/'
```

Current note:

```text
Line 1 was observed malformed: a bare OpenRouter key is prefixed to POSTGRES_DB.
Service is still healthy because docker-compose has defaults, but this should be cleaned.
```

Safe fix:

```bash
cd /opt/eris
cp .env .env.bak.$(date +%Y%m%d%H%M%S)
nano .env
```

Make the first line exactly:

```env
POSTGRES_DB=eris
```

Do not change any secret values while fixing the first line.

After env changes:

```bash
cd /opt/eris
docker compose up -d --build api
curl -i https://hugme2.com/health/detail
```

## Nginx / TLS

Primary config:

```text
/etc/nginx/conf.d/eris.conf
```

Check config:

```bash
nginx -t
nginx -T | sed -n '1,260p'
```

Certificate:

```text
/etc/letsencrypt/live/hugme2.com/fullchain.pem
/etc/letsencrypt/live/hugme2.com/privkey.pem
```

Check certificate:

```bash
certbot certificates
```

Known certificate:

```text
Domain: hugme2.com
Expires: 2026-08-10 01:31:21 UTC
```

Manual renewal dry run:

```bash
certbot renew --dry-run
```

If renewal succeeds:

```bash
systemctl reload nginx
```

## Database

Open psql:

```bash
docker exec -it eris-postgres psql -U eris -d eris
```

List tables:

```sql
\dt
```

Useful counts:

```bash
docker exec eris-postgres psql -U eris -d eris -c "select count(*) from users;"
docker exec eris-postgres psql -U eris -d eris -c "select count(*) from messages;"
docker exec eris-postgres psql -U eris -d eris -c "select count(*) from notification_tasks;"
```

Backup:

```bash
mkdir -p /opt/eris/backups
docker exec eris-postgres pg_dump -U eris -d eris \
  > /opt/eris/backups/eris_$(date +%Y%m%d_%H%M%S).sql
```

Restore to a fresh DB only:

```bash
docker exec -i eris-postgres psql -U eris -d eris < /opt/eris/backups/<backup>.sql
```

## Redis

Ping:

```bash
docker exec eris-redis redis-cli --pass "$REDIS_PASSWORD" ping
```

If running from host and env is loaded:

```bash
cd /opt/eris
source .env
docker exec eris-redis redis-cli --pass "$REDIS_PASSWORD" ping
```

Inspect context keys:

```bash
docker exec eris-redis redis-cli --pass "$REDIS_PASSWORD" keys 'ctx:*'
```

Avoid `FLUSHALL` unless explicitly resetting all transient context.

## Common Incidents

### API Unhealthy

```bash
docker ps
docker logs --tail 200 eris-api
cd /opt/eris
docker compose up -d --build api
curl -i http://127.0.0.1:8000/health/detail
```

If DB or Redis is down:

```bash
docker compose restart postgres redis
docker compose up -d --build api
```

### Public Site Down

```bash
curl -i http://127.0.0.1:8000/health
nginx -t
systemctl status nginx --no-pager -l
tail -100 /var/log/nginx/eris.error.log
systemctl reload nginx
```

### Telegram Webhook Failing

Check bot token exists, without printing it:

```bash
docker inspect eris-api --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep TELEGRAM_BOT_TOKEN \
  | sed -E 's/=.*/=***REDACTED***/'
```

Check Telegram webhook info:

```bash
curl -s https://hugme2.com/telegram/webhook/info
```

Check logs:

```bash
docker logs --tail 200 eris-api | grep telegram
```

### Stripe Webhook Failing

Check endpoint:

```text
https://hugme2.com/api/v1/billing/stripe/webhook
```

Current code may also expose:

```text
/api/v1/webhooks/stripe
```

Keep Stripe dashboard endpoint aligned with implemented backend route.

Check secret exists:

```bash
docker inspect eris-api --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep STRIPE_WEBHOOK_SECRET \
  | sed -E 's/=.*/=***REDACTED***/'
```

### WebSocket Tasks Not Showing

Connect:

```text
wss://hugme2.com/ws/operators/tasks?operator_id=debug
```

Check open tasks:

```bash
docker exec eris-postgres psql -U eris -d eris \
  -c "select id, priority, status, trigger_reason, created_at from handoff_tasks where closed_at is null order by created_at desc limit 20;"
```

Check logs:

```bash
docker logs --tail 200 eris-api | grep 'ws.operator'
```

### Notification Queue Stuck

List tasks:

```bash
curl -s 'http://127.0.0.1:8000/api/v1/notifications/tasks?status=pending&limit=50'
```

Cancel pending silent reactivation:

```sql
UPDATE notification_tasks
SET status = 'cancelled',
    failure_reason = 'manual rollback'
WHERE notification_type = 'silent_reactivation'
  AND status = 'pending';
```

## Rollback

Rollback Nginx config:

```bash
cp /etc/nginx/conf.d/eris.conf /etc/nginx/conf.d/eris.conf.bak.$(date +%Y%m%d%H%M%S)
nginx -t
systemctl reload nginx
```

Rollback app code requires restoring from backup or source control. Before risky edits:

```bash
cd /opt/eris
cp docker-compose.yml docker-compose.yml.bak.$(date +%Y%m%d%H%M%S)
tar -czf /opt/eris/backups/app_$(date +%Y%m%d_%H%M%S).tgz app docker-compose.yml *.md
```

## Release Checklist

Before `v0.1.0`:

- `https://hugme2.com/health/detail` returns all ok.
- Telegram webhook receives and stores a message.
- AI conversation works.
- Admin handoff can lock/reply/return.
- WebSocket task stream works.
- Stripe test payment works.
- Stripe webhook updates order/VIP.
- `notification_tasks` queue has no stuck test data.
- DB backup exists.
- `.env` contains no malformed lines.
- Runbook is updated.
