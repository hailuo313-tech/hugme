# C-09 检验报告：WebSocket 协议与实现一致性

**任务：** C-09 — 审查 `ws_protocol.md` 与实现一致性  
**结论：** **通过（协议 conformance 门禁绿）**  
**规范：** [`docs/ws_protocol.md`](ws_protocol.md)（与 `D5-4_WEBSOCKET_PROTOCOL.md` 对齐）

---

## 1. 执行摘要

| 项 | 结果 |
|----|------|
| 规范文档 | `docs/ws_protocol.md` |
| 实现 | `app/api/realtime.py` + `ws_operator_task_delta.py` |
| 服务端事件 | **6** 种（含 `user.upgraded`） |
| 客户端事件 | **2** 种 |
| 夹具校验 | **6** valid server + **2** client + **2** invalid 拒绝 |
| 既有单测 | `tests/test_realtime.py`（delta 语义） |

---

## 2. 一致性矩阵

| 规范项 | 文档 | 实现 | 状态 |
|--------|------|------|------|
| 路径 | `/ws/operators/tasks` | `realtime.operator_task_stream` | ✅ |
| 轮询间隔 | 1000 ms | `POLL_INTERVAL_SECONDS=1.0` | ✅ |
| 首包 snapshot | 仅一次 | 连接后单次 `task.snapshot` | ✅ |
| Delta 跟踪字段 | 4 字段 | `TRACKED_FIELDS` 一致 | ✅ |
| Open status 集合 | 4 状态 | `OPEN_TASK_STATUSES` 一致 | ✅ |
| ping → pong | 是 | `_handle_client_message` | ✅ |
| task.ack | 仅日志 | `ws.operator.task_ack` | ✅ |

---

## 3. 非阻塞遗留

- [ ] WebSocket `token=<jwt>` 鉴权（D5-1/D5-3）
- [ ] 轮询改 Redis / LISTEN/NOTIFY（规模化）
- [x] Admin 看板联调清单（C-10）— 见 `docs/C10_INSPECTION_REPORT.md`

---

## 4. 门禁

```powershell
.\scripts\check-c09-ws-protocol.ps1
```

---

## 5. 签署

| 检查项 | 结果 |
|--------|------|
| 协议文档归档 | 通过 |
| conformance 夹具 | 通过 |
| 实现常量对齐 | 通过 |
| delta 单测 | 通过 |
