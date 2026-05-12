# D5-4 WebSocket Task Push Protocol

Status: implemented as a minimal backend skeleton.

## Goal

Operators should receive high-priority handoff tasks in near real time. The first version polls `handoff_tasks` every 1 second from the WebSocket worker, which avoids cross-worker in-memory broadcast issues while the API runs with multiple Uvicorn workers.

## Endpoint

```text
GET /ws/operators/tasks?operator_id=<operator-id>&trace_id=<optional-trace-id>
```

Use the public domain:

```text
wss://hugme2.com/ws/operators/tasks?operator_id=<operator-id>
```

Authentication is intentionally left as a D5-1/D5-3 integration point. Once operator JWT is available, pass it as:

```text
wss://hugme2.com/ws/operators/tasks?operator_id=<operator-id>&token=<operator-jwt>
```

The server currently accepts without token so the admin UI can wire the stream early.

## Server Events

`connection.ready`

```json
{
  "type": "connection.ready",
  "trace_id": "ws-op-1",
  "operator_id": "op-1",
  "poll_interval_ms": 1000
}
```

`task.snapshot`

```json
{
  "type": "task.snapshot",
  "trace_id": "ws-op-1",
  "tasks": []
}
```

`task.upsert`

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
    "created_at": "2026-05-12T04:00:00",
    "last_message_at": "2026-05-12T04:00:00",
    "channel": "telegram",
    "external_id": "tg_123",
    "risk_level": "normal"
  }
}
```

`pong`

```json
{
  "type": "pong",
  "trace_id": "ws-op-1"
}
```

## Client Events

`ping`

```json
{ "type": "ping" }
```

`task.ack`

```json
{
  "type": "task.ack",
  "task_id": "uuid"
}
```

`task.ack` is logged only in the first version. D5-3 owns the lock/ack semantics.

## Task Selection

The stream sends open tasks from `handoff_tasks` where:

- `status in ('pending', 'PENDING', 'ESCALATED', 'HUMAN_LOCKED')`
- `closed_at is null`

Tasks are ordered by priority:

```text
P0 -> P1 -> P2 -> P3
```

Then by newest `created_at`.

## Integration Notes

- D5-3 should update `handoff_tasks.status`, `assigned_operator_id`, `locked_at`, and `closed_at`.
- Admin UI should connect once after login and render `task.upsert`.
- For production scale, replace 1 second polling with Redis pub/sub or Postgres `LISTEN/NOTIFY` after the task semantics stabilize.
