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

## Monitoring and Alerting (D7-1 / D7-2)

Metrics endpoint:

```bash
curl -s http://127.0.0.1:8000/metrics | head -3
```

Start the optional monitoring stack from the repository root after the main ERIS stack is running:

```bash
cd /opt/eris
docker compose -f monitoring/docker-compose.monitoring.yml up -d
```

Check Prometheus targets:

```bash
curl -s http://127.0.0.1:9090/api/v1/targets \
  | jq '.data.activeTargets[] | {job: .labels.job, health: .health}'
```

Expected healthy jobs:

```text
eris-api
eris-postgres
eris-redis
```

Grafana is bound to localhost by default:

```text
http://127.0.0.1:3000
```

Before first use, set these in `/opt/eris/.env` and do not keep the default password:

```env
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=change_me_before_use
```

### Discord Alert Webhook

To get a Discord webhook URL:

1. Open the Discord server and choose the ops channel.
2. Go to channel settings.
3. Open Integrations.
4. Create a webhook.
5. Copy the webhook URL.
6. Put it in `/opt/eris/.env`:

```env
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

Restart Alertmanager after changing the webhook:

```bash
docker compose -f monitoring/docker-compose.monitoring.yml up -d alertmanager
```

If `DISCORD_WEBHOOK_URL` is empty, the monitoring compose template routes critical alerts to a disabled localhost URL so alerts do not accidentally leave the server.

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
