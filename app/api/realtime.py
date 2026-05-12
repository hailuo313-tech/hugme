import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger
from sqlalchemy import text

from core.database import AsyncSessionLocal

router = APIRouter()

OPEN_TASK_STATUSES = ("pending", "PENDING", "ESCALATED", "HUMAN_LOCKED")
POLL_INTERVAL_SECONDS = 1.0


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value is not None else None


async def _fetch_open_tasks() -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            text(
                """
                SELECT
                    ht.id,
                    ht.user_id,
                    ht.conversation_id,
                    ht.priority,
                    ht.trigger_reason,
                    ht.status,
                    ht.assigned_operator_id,
                    ht.locked_at,
                    ht.closed_at,
                    ht.created_at,
                    c.last_message_at,
                    c.channel,
                    u.external_id,
                    u.risk_level
                FROM handoff_tasks ht
                LEFT JOIN conversations c ON c.id = ht.conversation_id
                LEFT JOIN users u ON u.id = ht.user_id
                WHERE ht.status = ANY(:statuses)
                  AND ht.closed_at IS NULL
                ORDER BY
                    CASE ht.priority
                        WHEN 'P0' THEN 0
                        WHEN 'P1' THEN 1
                        WHEN 'P2' THEN 2
                        ELSE 3
                    END,
                    ht.created_at DESC
                LIMIT 50
                """
            ),
            {"statuses": list(OPEN_TASK_STATUSES)},
        )).mappings().all()

    tasks = []
    for row in rows:
        tasks.append({
            "task_id": str(row["id"]),
            "user_id": _json_value(row["user_id"]),
            "conversation_id": _json_value(row["conversation_id"]),
            "priority": row["priority"] or "P3",
            "trigger_reason": row["trigger_reason"],
            "status": row["status"],
            "assigned_operator_id": _json_value(row["assigned_operator_id"]),
            "locked_at": _json_value(row["locked_at"]),
            "closed_at": _json_value(row["closed_at"]),
            "created_at": _json_value(row["created_at"]),
            "last_message_at": _json_value(row["last_message_at"]),
            "channel": row["channel"],
            "external_id": row["external_id"],
            "risk_level": row["risk_level"],
        })
    return tasks


def _snapshot_key(tasks: list[dict[str, Any]]) -> tuple[tuple[str, str, str | None], ...]:
    return tuple((task["task_id"], task["status"], task["assigned_operator_id"]) for task in tasks)


@router.websocket("/ws/operators/tasks")
async def operator_task_stream(websocket: WebSocket):
    operator_id = websocket.query_params.get("operator_id") or "anonymous"
    trace_id = websocket.query_params.get("trace_id") or f"ws-{operator_id}"
    log = logger.bind(trace_id=trace_id, operator_id=operator_id, path="/ws/operators/tasks")

    await websocket.accept()
    log.info("ws.operator.connected")
    await websocket.send_json({
        "type": "connection.ready",
        "trace_id": trace_id,
        "operator_id": operator_id,
        "poll_interval_ms": int(POLL_INTERVAL_SECONDS * 1000),
    })

    last_snapshot: tuple[tuple[str, str, str | None], ...] | None = None
    try:
        while True:
            try:
                client_msg = await asyncio.wait_for(websocket.receive_json(), timeout=0.01)
                msg_type = client_msg.get("type")
                if msg_type == "ping":
                    await websocket.send_json({"type": "pong", "trace_id": trace_id})
                elif msg_type == "task.ack":
                    log.bind(task_id=client_msg.get("task_id")).info("ws.operator.task_ack")
            except asyncio.TimeoutError:
                pass

            tasks = await _fetch_open_tasks()
            snapshot = _snapshot_key(tasks)
            if snapshot != last_snapshot:
                await websocket.send_json({
                    "type": "task.snapshot",
                    "trace_id": trace_id,
                    "tasks": tasks,
                })
                for task in tasks:
                    await websocket.send_json({
                        "type": "task.upsert",
                        "trace_id": trace_id,
                        "task": task,
                    })
                log.bind(task_count=len(tasks)).info("ws.operator.tasks_pushed")
                last_snapshot = snapshot

            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        log.info("ws.operator.disconnected")
