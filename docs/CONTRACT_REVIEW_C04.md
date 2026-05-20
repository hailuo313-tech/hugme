# schema_spec.json 与适配器接口契约评审（C-04）

**任务：** C-04 — 审查 `schema_spec.json` 与适配器接口契约  
**结论：** **无阻塞项（设计评审通过）**  
**验收：** 契约评审记录归档（本文档 + `docs/schema_spec.json` + 参考实现）

---

## 1. 评审范围

| 项 | 状态 |
|----|------|
| `docs/schema_spec.json` | C-04 定稿（对齐 P1-13 描述） |
| `app/services/inbound/envelope.py` | Pydantic 模型 + JSON Schema 校验 |
| `app/services/inbound/adapter_protocol.py` | `ChannelAdapter` Protocol + 入队参考 |
| 现有 D1-2 `InboundMessageRequest` | 已评审映射路径，保持 HTTP API 稳定 |
| P1-14 Telethon 适配器实现 | **未实现**（非阻塞，见 §6） |

---

## 2. 标准入站信封（schema_spec.json）

### 2.1 字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `platform` | 是 | `telegram_real_user` \| `telegram` \| `web` \| `app` |
| `account_id` | MTProto 必填 | 账号池 id（P1-09 / C-15 路由） |
| `sender_phone` | 否 | MTProto 联系人电话（有则填） |
| `external_user_id` | 是 | 稳定用户键，如 `tg_{id}` |
| `message_type` | 是 | text / image / voice 等 |
| `content` | 是 | 正文或占位描述，≤8000 |
| `metadata` | 否 | `telegram_message_id` 用于 P1-12 去重 |
| `trace_id` | 是 | 与 `ops/observability/logging-spec.md` 一致 |

### 2.2 与 P1-13 对齐

- 含 **`account_id`**、**`sender_phone`**（P1-13 任务卡要求）  
- `platform=telegram_real_user` 时 JSON Schema **条件必填** `account_id` 与 `metadata.telegram_message_id`

---

## 3. 适配器契约（ChannelAdapter）

```text
raw_event  →  normalize()  →  StandardInboundEnvelope
                              →  validate_envelope()  →  inbound_queue (XADD)
```

| 实现方 | platform | 状态 |
|--------|----------|------|
| MTProto / Telethon（P1-14） | `telegram_real_user` | 待实现 |
| Bot Webhook 桥接（可选） | `telegram` | 当前走 `telegram.py` 直处理，可后续桥接到队列 |
| H5/App mock（P1-15） | `web` / `app` | 待实现 |

**禁止：** 适配器直接写 DB 绕过标准信封（P1-16 统一消费 `inbound_queue`）。

---

## 4. 与现有代码的差异（非阻塞）

| 现状 | 标准契约 | 处理 |
|------|----------|------|
| HTTP 用 `channel` | 队列用 `platform` | `from_legacy_http_inbound()` 映射；HTTP 字段名暂不破坏 |
| Bot 路径无 `account_id` | MTProto 必填 | Bot 保持 `platform=telegram`，无 account_id |
| 无 `inbound_queue` 消费者 | XADD 字段见 `to_queue_fields()` | P1-06 实现时复用 |
| `ctx:{conversation_id}` | P1-19 规划 `conv:{user_id}` | 文档记录，合并时统一 |

---

## 5. 安全与合规

- 日志不得输出 `sender_phone` 明文（沿用 C-15 `redact_sensitive`）  
- `metadata` 允许扩展字段，`additionalProperties: true` 仅限 metadata 对象  
- 信封 **`additionalProperties: false`** 防止未评审字段静默入库

---

## 6. P1-14 / P1-15 复验清单（实现合并前）

- [ ] MTProto `normalize()` 产出通过 `validate_against_schema_spec`
- [ ] `account_id` 来自 `assign_account_id()`（`app/services/mtproto/account_routing.py`）
- [ ] 去重键 `telegram_msg:{user_id}:{message_id}` 与 metadata 一致
- [ ] 单测：`tests/test_schema_spec_c04.py` 扩展真实 Telethon fixture（mock 即可）

---

## 7. 门禁

```powershell
.\scripts\check-schema-contract.ps1
```

---

## 8. 结论

| 项 | 结果 |
|----|------|
| schema_spec.json 完整性 | 通过 |
| 适配器 Protocol 清晰度 | 通过 |
| 与 D1-2 兼容策略 | 通过 |
| **阻塞项** | **无** |
