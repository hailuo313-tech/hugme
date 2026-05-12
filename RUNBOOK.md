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
