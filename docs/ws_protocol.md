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

| `type` | Required fields | Notes |
|--------|-----------------|-------|
| `connection.ready` | `trace_id`, `operator_id`, `poll_interval_ms` | `poll_interval_ms` = 1000 |
| `task.snapshot` | `trace_id`, `tasks` | `tasks` is array of task objects |
| `task.upsert` | `trace_id`, `task` | Single task per message |
| `task.removed` | `trace_id`, `task_id` | Task left the open-task selection |
| `pong` | `trace_id` | Reply to client `ping` |
| `user.upgraded` | `trace_id`, `user_id`, `previous_level`, `new_level`, `reason`, `upgraded_at` | Broadcast to all connections |

## Task Object

Required keys for `task.snapshot` and `task.upsert`:

`task_id`, `user_id`, `conversation_id`, `priority`, `trigger_reason`, `status`,
`assigned_operator_id`, `locked_at`, `closed_at`, `created_at`, `last_message_at`,
`channel`, `external_id`, `risk_level`

Tracked fields for delta (`task.upsert`):

`status`, `assigned_operator_id`, `priority`, `last_message_at`

## Client Events

| `type` | Required fields |
|--------|-----------------|
| `ping` | `type` only |
| `task.ack` | `task_id` |

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

See `fixtures/c09_ws_protocol.json` and `docs/C09_INSPECTION_REPORT.md`.
