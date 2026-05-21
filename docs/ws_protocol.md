# WebSocket Operator Task Protocol (`ws_protocol.md`)

**Status:** P4-01 signed protocol for frontend/backend review; canonical for C-09 conformance.
**Implementation:** `app/api/realtime.py`, `app/services/ws_operator_task_delta.py`
**Review signoff:** Backend API owner: approved. Frontend dashboard owner: approved.

## Endpoint

```text
GET /ws/operators/tasks?operator_id=<operator-id>&trace_id=<optional>
wss://hugme2.com/ws/operators/tasks?operator_id=<operator-id>
```

Future auth (D5-1/D5-3): `&token=<operator-jwt>`; not enforced in current backend.

## Lifecycle

1. Client connects.
2. Server sends `connection.ready`.
3. Server sends **one** `task.snapshot` with the full open-task list.
4. Server sends delta events only: `task.upsert` / `task.removed`.
5. Client may send `ping`; server responds with `pong`. Client may send `task.ack` (logged only).
6. Optional broadcast: `user.upgraded` (P2-11).

After the initial snapshot, clients must apply deltas; there is no second snapshot.

## Server Events

|| `type` | Required fields | Notes |
||--------|-----------------|-------|
|| `connection.ready` | `trace_id`, `operator_id`, `poll_interval_ms` | `poll_interval_ms` = 1000 |
|| `task.snapshot` | `trace_id`, `tasks` | `tasks` is array of task objects |
|| `task.upsert` | `trace_id`, `task` | Single task per message |
|| `task.removed` | `trace_id`, `task_id` | Task left the open-task selection |
|| `pong` | `trace_id` | Reply to client `ping` |
|| `user.upgraded` | `trace_id`, `user_id`, `previous_level`, `new_level`, `reason`, `upgraded_at` | Broadcast to all connections |
|| `user.alert` | `trace_id`, `user_id`, `level`, `nickname`, `external_id`, `message_id`, `reason`, `alerted_at` | P4-06: S/A 级用户全屏弹窗提醒 |

## Task Object

Required keys for `task.snapshot` and `task.upsert`:

`task_id`, `user_id`, `conversation_id`, `priority`, `trigger_reason`, `status`,
`assigned_operator_id`, `locked_at`, `closed_at`, `created_at`, `last_message_at`,
`channel`, `external_id`, `risk_level`

Tracked fields for delta (`task.upsert`):

`status`, `assigned_operator_id`, `priority`, `last_message_at`

## Client Events

|| `type` | Required fields |
||--------|-----------------|
|| `ping` | `type` only |
|| `task.ack` | `task_id` |

## Frontend Contract

- The dashboard must treat `task.snapshot` as the initial authoritative state.
- After the snapshot, the dashboard must apply `task.upsert` and `task.removed` incrementally.
- Unknown event `type` values must be ignored and logged client-side.
- `task_id` is the stable key for list rendering, acknowledgement, locking, and detail navigation.
- Reconnect behavior: on disconnect, reconnect and wait for a new `connection.ready` and fresh `task.snapshot`.

## Backend Contract

- The backend must include `trace_id` on every server event.
- `task.upsert` must include the complete task object, not a partial patch.
- `task.removed` must be emitted when an open task leaves the open-task selection.
- Server polling interval is currently 1000 ms and is announced as `poll_interval_ms`.
- `task.ack` is observability-only; it must not mutate task assignment or lock state.

## Open Task Selection

- `status IN ('pending', 'PENDING', 'ESCALATED', 'HUMAN_LOCKED')`
- `closed_at IS NULL`
- Order: P0, P1, P2, P3, then `created_at DESC`
- Limit 50 per poll

## Signed Acceptance

P4-01 acceptance is met when:

- Backend and frontend agree to this document as the wire contract.
- `scripts/check-c09-ws-protocol.ps1` passes.
- `tests/test_c09_ws_protocol.py` and `tests/test_realtime.py` pass.
- Any future protocol change updates this document and the conformance fixture in the same PR.

## Conformance Gate

```powershell
.\scripts\check-c09-ws-protocol.ps1
```

## P4-02: ACK 重推机制 (2026-05-21)

### 新增客户端事件

||| `type` | Required fields |
|||--------|-----------------|
||| `message.ack` | `message_id` |

### 服务器消息变更

除 `connection.ready`, `task.snapshot`, `pong` 外，所有服务器消息现在包含 `message_id` 字段：

- 服务器发送消息时自动生成 `message_id` 并跟踪确认状态
- 客户端收到消息后应发送 `message.ack` 确认
- 未确认的消息将在 5 秒后自动重推，最多重试 3 次
- 30 秒未确认的消息将被放弃并记录警告日志

### 示例

```json
// 服务器发送（自动添加 message_id）
{
  "type": "task.upsert",
  "trace_id": "ws-op-1",
  "message_id": "task.upsert-a1b2c3d4",
  "task": {...}
}

// 客户端确认
{
  "type": "message.ack",
  "message_id": "task.upsert-a1b2c3d4"
}
```

### 兼容性

- 旧的 `task.ack` 仍然支持，但建议使用新的 `message.ack`
- 广播消息（如 `user.upgraded`）也支持 ACK 重推机制

## P4-06: S/A 级用户全屏弹窗提醒 (2026-05-21)

### 新增服务器事件

|| `type` | Required fields | Notes |
||--------|-----------------|-------|
|| `user.alert` | `trace_id`, `user_id`, `level`, `nickname`, `external_id`, `message_id`, `reason`, `alerted_at` | S/A 级用户全屏弹窗提醒，支持 ACK 确认 |

### 事件说明

- 当 S 或 A 级用户需要坐席立即关注时，服务器发送 `user.alert` 事件
- 前端收到事件后显示全屏弹窗并播放声音提醒
- 坐席点击"立即查看"后发送 `message.ack` 确认并跳转到用户详情
- 坐席点击"稍后处理"仅关闭弹窗，不发送 ACK

### 示例

```json
// 服务器发送
{
  "type": "user.alert",
  "trace_id": "ws-op-1",
  "message_id": "user.alert-xyz123",
  "user_id": "user_123",
  "level": "S",
  "nickname": "VIP 用户",
  "external_id": "telegram_123456",
  "reason": "用户升级为 S 级",
  "alerted_at": "2026-05-21T00:42:00Z"
}

// 客户端确认（坐席点击"立即查看"时发送）
{
  "type": "message.ack",
  "message_id": "user.alert-xyz123"
}
```

### 兼容性

- 此事件依赖 P4-02 的 ACK 重推机制
- 仅对 S 和 A 级用户触发，B/C/D 级用户不触发

See `fixtures/c09_ws_protocol.json` and `docs/C09_INSPECTION_REPORT.md`.