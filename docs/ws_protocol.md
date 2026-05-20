# WebSocket Operator Task Protocol (`ws_protocol.md`)

**Status:** Canonical wire spec for P4-01 / C-09 (aligned with `D5-4_WEBSOCKET_PROTOCOL.md`).  
**Implementation:** `app/api/realtime.py`, `app/services/ws_operator_task_delta.py`

## Endpoint

```text
GET /ws/operators/tasks?operator_id=<operator-id>&trace_id=<optional>
wss://hugme2.com/ws/operators/tasks?operator_id=<operator-id>
```

Future auth (D5-1/D5-3): `&token=<operator-jwt>` — not enforced in current backend.

## Lifecycle

1. Client connects.
2. Server → `connection.ready`
3. Server → **one** `task.snapshot` (full open-task list)
4. Server → delta only: `task.upsert` / `task.removed`
5. Client may send `ping` → `pong`, `task.ack` (logged only)
6. Optional broadcast: `user.upgraded` (P2-11)

After the initial snapshot, clients must apply deltas; there is no second snapshot.

## Server events

| `type` | Required fields | Notes |
|--------|-----------------|-------|
| `connection.ready` | `trace_id`, `operator_id`, `poll_interval_ms` | `poll_interval_ms` = 1000 |
| `task.snapshot` | `trace_id`, `tasks` | `tasks` is array of task objects |
| `task.upsert` | `trace_id`, `task` | Single task per message |
| `task.removed` | `trace_id`, `task_id` | |
| `pong` | `trace_id` | Reply to client `ping` |
| `user.upgraded` | `trace_id`, `user_id`, `previous_level`, `new_level`, `reason`, `upgraded_at` | Broadcast to all connections |

## Task object (snapshot / upsert)

Required keys:

`task_id`, `user_id`, `conversation_id`, `priority`, `trigger_reason`, `status`,
`assigned_operator_id`, `locked_at`, `closed_at`, `created_at`, `last_message_at`,
`channel`, `external_id`, `risk_level`

Tracked fields for delta (`task.upsert`): `status`, `assigned_operator_id`, `priority`, `last_message_at`

## Client events

| `type` | Required fields |
|--------|-----------------|
| `ping` | `type` only |
| `task.ack` | `task_id` |

## Open task selection (implementation)

- `status IN ('pending', 'PENDING', 'ESCALATED', 'HUMAN_LOCKED')`
- `closed_at IS NULL`
- Order: P0 → P1 → P2 → P3, then `created_at DESC`
- Limit 50 per poll

## Conformance gate

```powershell
.\scripts\check-c09-ws-protocol.ps1
```

See `fixtures/c09_ws_protocol.json` and `docs/C09_INSPECTION_REPORT.md`.
