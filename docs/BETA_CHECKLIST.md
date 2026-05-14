# ERIS v0.1.0 Beta Checklist

Use this checklist to invite the first five beta users without needing an
engineer in the loop.

## 1. Preflight

> **运营后台 UI 检查**：除下方服务器命令外，还需完成
> [`docs/ADMIN_BETA_PREFLIGHT.md`](./ADMIN_BETA_PREFLIGHT.md) 的 §1–§7
> 全部步骤（约 5 分钟），确认后台可正常登录、查看会话、退出，再邀请用户。

Run these checks before sending any invite:

```bash
curl -s https://hugme2.com/health/detail
ssh -i C:\Users\13267\.ssh\eris_67.216.204.137 -p 2222 root@67.216.204.137
cd /opt/eris
docker compose ps
ls -lh /opt/eris/backups/eris_backup_*.tar.gz | tail -n 3
```

Expected:

- `/health/detail` shows `api`, `db`, and `redis` as `ok`.
- `eris-api`, `eris-postgres`, and `eris-redis` are healthy.
- At least one fresh backup exists in `/opt/eris/backups/`.

Do not invite users if health or backup checks fail.

## 2. Invite Five Beta Users

Invite users one at a time. Wait until user 1 finishes onboarding before
inviting user 2.

Message template:

```text
你是 ERIS v0.1.0 的小范围内测用户。

打开 Telegram，搜索并添加我们的 bot：<填入 BotFather username>
发送 /start，然后按提示完成 5 个问题。

今天只需要做三件事：
1. 完成 onboarding。
2. 和 Aria 连续聊 10 分钟。
3. 如果卡住或回复奇怪，把截图发给我。

这是内测，不要输入真实身份证、银行卡、住址等敏感信息。
```

For each user, record:

```text
beta_user_1:
  telegram_handle:
  invited_at:
  onboarding_done_at:
  first_issue:
```

Stop at five users for v0.1.0.

## 3. First-Day Metrics

Check these during the first day: after each invite, then at +1h, +4h, and +24h.

```bash
docker exec eris-postgres psql -U eris -d eris -c "
SELECT
  COUNT(*) AS users_total,
  COUNT(*) FILTER (WHERE gdpr_consent_at IS NOT NULL) AS onboarding_completed
FROM users;"

docker exec eris-postgres psql -U eris -d eris -c "
SELECT sender_type, COUNT(*)
FROM messages
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY sender_type
ORDER BY sender_type;"

docker exec eris-postgres psql -U eris -d eris -c "
SELECT state, COUNT(*)
FROM conversations
GROUP BY state
ORDER BY state;"

docker exec eris-postgres psql -U eris -d eris -c "
SELECT status, COUNT(*)
FROM handoff_tasks
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY status
ORDER BY status;"

docker exec eris-postgres psql -U eris -d eris -c "
SELECT status, COUNT(*)
FROM orders
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY status
ORDER BY status;"
```

Watch:

- Onboarding completion: every invited user should reach `gdpr_consent_at`.
- Reply continuity: `messages.sender_type='assistant'` should grow after user
  messages.
- Handoff health: no task should stay `HUMAN_LOCKED` longer than 15 minutes.
- Stripe health: Checkout orders can stay `pending` unless a test payment is
  intentionally completed.
- System health: `/health/detail` must remain all `ok`.

## 4. Smoke Commands During Beta

Telegram flow:

```bash
docker logs --tail 200 eris-api | grep -E 'tg.webhook|onboarding|orchestrator'
```

Admin:

```bash
TOKEN=$(cat /root/.eris_admin_pw_20260513.txt | xargs -I{} curl -s -X POST http://127.0.0.1:8000/api/v1/admin/login \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"admin\",\"password\":\"{}\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/v1/admin/conversations?page=1&page_size=5" \
  | python3 -m json.tool
```

E2E regression:

```bash
cd /opt/eris
API_BASE=http://127.0.0.1:8000 bash scripts/e2e/run.sh
```

## 5. Issue Triage

Use this order:

1. Check `/health/detail`.
2. Check `docker compose ps`.
3. Check API logs for the user's `external_id` or latest `trace_id`.
4. Check DB rows in `users`, `user_profiles`, `conversations`, and `messages`.
5. Decide whether to keep testing, pause new invites, or roll back.

Pause invites if:

- `/health/detail` is not all `ok`.
- Two users fail onboarding.
- Assistant replies fail for more than 10 minutes.
- Any data-loss symptom appears.

## 6. Rollback

Rollback app code to the previous stable tag or commit:

```bash
cd /opt/eris
git fetch --tags origin
git log --oneline -n 10
git checkout <previous-stable-sha-or-tag>
docker compose up -d --build api
curl -s http://127.0.0.1:8000/health/detail
```

If rollback is needed after v0.1.0 is tagged, preserve evidence first:

```bash
mkdir -p /opt/eris/backups/incidents
docker logs --tail 500 eris-api > /opt/eris/backups/incidents/api_$(date -u +%Y%m%dT%H%M%SZ).log
docker exec eris-postgres pg_dump -U eris -d eris --format=custom \
  > /opt/eris/backups/incidents/pre_rollback_$(date -u +%Y%m%dT%H%M%SZ).dump
```

After rollback, stop new invites until:

- `/health/detail` is all `ok`.
- One internal `/start` onboarding run succeeds.
- Admin conversation list loads.
- The incident note is added to `RUNBOOK.md` or the next release notes.
