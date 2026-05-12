# D5-4 WebSocket Task Push Protocol

Status: backend implementation hardened in 2026-05 PR (delta semantics + tests).

## Goal

Operators should receive high-priority handoff tasks in near real time. The
first version polls `handoff_tasks` every 1 second from the WebSocket worker,
which avoids cross-worker in-memory broadcast issues while the API runs with
multiple Uvicorn workers.

## Endpoint

```text
GET /ws/operators/tasks?operator_id=<operator-id>&trace_id=<optional-trace-id>
```

Use the public domain:

```text
wss://hugme2.com/ws/operators/tasks?operator_id=<operator-id>
```

Authentication is intentionally left as a D5-1/D5-3 integration point. Once
operator JWT is available, pass it as:

```text
wss://hugme2.com/ws/operators/tasks?operator_id=<operator-id>&token=<operator-jwt>
```

The server currently accepts without token so the admin UI can wire the stream
early.

## Lifecycle

1. Client opens the WebSocket connection.
2. Server sends `connection.ready`.
3. Server sends **one** `task.snapshot` with the full current open-task list.
4. While connected the server pushes deltas only:
   - `task.upsert` — new task or any tracked field changed
     (`status`, `assigned_operator_id`, `priority`, `last_message_at`).
   - `task.removed` — task is no longer open (closed / out of selection window).
5. Client may send `ping` (server replies with `pong`) and `task.ack` (logged only).
6. Client disconnect ends the stream.

There is intentionally only ever **one** `task.snapshot` per connection
(the initial one). After that the stream is delta-only; the client must
reconstruct state by applying `task.upsert` / `task.removed`.

## Server Events

### `connection.ready`

```json
{
  "type": "connection.ready",
  "trace_id": "ws-op-1",
  "operator_id": "op-1",
  "poll_interval_ms": 1000
}
```

### `task.snapshot` (initial only)

```json
{
  "type": "task.snapshot",
  "trace_id": "ws-op-1",
  "tasks": []
}
```

### `task.upsert` (delta)

```json
{
  "type": "task.upsert",
  "trace_id": "ws-op-1",
  "task": {
    "task_id": "uuid",
    "user_id": "uuid",
    "conversation_id": "uuid",
    "priority": "P1",
    "trigger_reason": "keyword_risk",
    "status": "pending",
    "assigned_operator_id": null,
    "locked_at": null,
    "closed_at": null,
    "created_at": "2026-05-12T04:00:00",
    "last_message_at": "2026-05-12T04:00:00",
    "channel": "telegram",
    "external_id": "tg_123",
    "risk_level": "normal"
  }
}
```

### `task.removed` (delta)

```json
{
  "type": "task.removed",
  "trace_id": "ws-op-1",
  "task_id": "uuid"
}
```

### `pong`

```json
{
  "type": "pong",
  "trace_id": "ws-op-1"
}
```

## Client Events

### `ping`

```json
{ "type": "ping" }
```

### `task.ack`

```json
{
  "type": "task.ack",
  "task_id": "uuid"
}
```

`task.ack` is logged only; the lock/ack semantics belong to D5-3.

## Task Selection

The stream sends open tasks from `handoff_tasks` where:

- `status in ('pending', 'PENDING', 'ESCALATED', 'HUMAN_LOCKED')`
- `closed_at is null`

Tasks are ordered by priority:

```text
P0 -> P1 -> P2 -> P3
```

Then by newest `created_at`.

## Logging

| Event | When | Notes |
|---|---|---|
| `ws.operator.connected` | After `accept()` | trace_id + operator_id |
| `ws.operator.snapshot_sent` | After initial snapshot | `task_count` |
| `ws.operator.tasks_pushed` | After any delta batch | `upsert_count`, `removed_count` |
| `ws.operator.task_ack` | Client `task.ack` received | `task_id` |
| `ws.operator.fetch_failed` | DB fetch raised | `error_type` (continues polling) |
| `ws.operator.initial_fetch_failed` | First fetch raised | empty snapshot sent |
| `ws.operator.disconnected` | `WebSocketDisconnect` | |

## Integration Notes

- Delta computation (`diff_tasks`, tracked fields) lives in
  `app/services/ws_operator_task_delta.py` so unit tests do not import
  `api.realtime` (which pulls FastAPI + SQLAlchemy).
- D5-3 should update `handoff_tasks.status`, `assigned_operator_id`,
  `locked_at`, and `closed_at`. The stream picks those changes up via the
  tracked-field diff.
- Admin UI should connect once after login, apply `task.snapshot` as initial
  state, and then mutate that state via `task.upsert` / `task.removed`.
- For production scale, the 1-second polling can be replaced with Redis pub/sub
  or Postgres `LISTEN/NOTIFY` once the task semantics stabilize. The wire
  protocol above is intentionally agnostic to the source — only the polling
  loop in `app/api/realtime.py` needs to change.
