# P4-07: WebSocket Client Reconnect Verification

## Scope

Operator dashboard WebSocket client recovers from dropped `/ws/operators/tasks`
connections within 10 seconds.

## Implementation

- `admin/lib/wsReconnect.ts`
  - `WS_RECONNECT_INITIAL_DELAY_MS = 1000`
  - `WS_RECONNECT_MAX_DELAY_MS = 8000`
  - `WS_RECONNECT_RECOVERY_SLA_MS = 10000`
- `admin/hooks/useOperatorTaskWs.ts`
  - enters `reconnecting` immediately on close
  - clears stale timers before opening a new socket
  - closes stale sockets without letting old `onclose` handlers schedule duplicate reconnects
  - resets retry attempts on `onopen`
  - re-applies `task.snapshot`, `task.upsert`, and `task.removed` after reconnect
- `admin/components/OperatorWsStatus.tsx`
  - exposes manual reconnect while disconnected or reconnecting

## Acceptance

- Automatic reconnect is scheduled at 1s, 2s, 4s, then capped at 8s.
- The retry cap is under the 10s recovery requirement.
- A fresh `task.snapshot` is accepted after reconnect so dashboard state can be rebuilt.

## Verification

- `npm.cmd exec tsc -- --noEmit --project tsconfig.json`
- `npm.cmd run build`
- `node scripts/check-bf-html.js docs/product/business-flow.html`
- P4-07 source contract check for reconnect constants, hook scheduling, snapshot handling, and manual reconnect state.

