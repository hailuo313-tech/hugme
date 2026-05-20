# MTProto / Telethon 安全评审（C-15）

**任务：** C-15 — 审查 Session 存储、密钥与账号隔离  
**结论：** **无阻塞项（设计评审通过）**  
**范围：** 仓库内 C-03 配置与参考实现；P1-18 合并前须复验 §7。

## 1. 威胁模型（摘要）

| 资产 | 风险 | 缓解 |
|------|------|------|
| StringSession | 泄露即账号接管 | 生产仅 DB 密文；Fernet；禁日志明文 |
| API_HASH | 滥用 | 仅环境变量，不进 Git |
| 多账号池 | Redis 串键 | account_id 路由 + 前缀隔离 |

## 2. Session 存储

- **development：** `TELEGRAM_SESSION_STRINGS` 或 `TELEGRAM_SESSION_DIR` 明文（本机）
- **production：** PostgreSQL `session_ciphertext`；**禁止** 非空 `TELEGRAM_SESSION_STRINGS`
- 加密：**Fernet**（`TELEGRAM_SESSION_FERNET_KEY`），实现见 `app/services/mtproto/session_crypto.py`
- DDL 草图：`docs/sketches/telegram_accounts_P1-09.sql`

## 3. 密钥管理

Fernet 与 DB 同级保护；轮换需批量重加密。日志经 `redact_sensitive` / `assert_safe_log_message`。

## 4. 账号隔离

- `assign_account_id(user_id, pool)` 稳定哈希选账号
- Redis：`mtproto:route:{user_id}`，`mtproto:acct:{account_id}:`
- 每 account_id 独立 Telethon client，禁止单 client 切换 auth_key

## 5. 门禁

`scripts/check-mtproto-security.ps1` — 生产 env 禁止明文 Session + pytest

## 6. P1-18 复验（合并前）

- [ ] 生产仅 decrypt → 内存
- [ ] 日志脱敏
- [ ] AccountPool 使用 routing + Redis 前缀
- [ ] 集成测试无真实 StringSession

## 7. 结论

| 项 | 结果 |
|----|------|
| 阻塞项 | **无** |
