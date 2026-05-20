"""
D5-4: Operator task push over WebSocket

GET /ws/operators/tasks?operator_id=<id>&trace_id=<optional>

协议（与 D5-4_WEBSOCKET_PROTOCOL.md 对齐）
------------------------------------------
连接首次：
    1. server → ``connection.ready``
    2. server → ``task.snapshot``（全量当前 open tasks）
之后（基于 1 秒轮询 ``handoff_tasks``）：
    - 新任务出现 / 已有任务状态或 assignee 变化 → ``task.upsert``（单条）
    - 任务关闭（``closed_at`` 已设 或 不再返回） → ``task.removed``（单条）
客户端：
    - ``ping`` → server 回 ``pong``
    - ``task.ack`` → 仅记日志（lock/ack 语义留给 D5-3）

鉴权 ``token=<jwt>`` 现阶段未启用（spec 标注 D5-1/D5-3 集成点）。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger
from sqlalchemy import text

from core.database import AsyncSessionLocal
from services.ws_operator_task_delta import diff_tasks

router = APIRouter()

OPEN_TASK_STATUSES = ("pending", "PENDING", "ESCALATED", "HUMAN_LOCKED")
POLL_INTERVAL_SECONDS = 1.0
CLIENT_RECV_TIMEOUT_SECONDS = 0.01  # 非阻塞收客户端消息


# ── 数据获取 ──────────────────────────────────────────


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value is not None else None


async def _fetch_open_tasks() -> list[dict[str, Any]]:
    """从 handoff_tasks 取当前未关闭任务。返回列表，按 spec 排序。

    本函数在测试里会被 monkeypatch 替换，所以保持纯异步、无副作用。
    """
    async with AsyncSessionLocal() as db:
        rows = (
            (
                await db.execute(
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
                )
            )
            .mappings()
            .all()
        )

    tasks: list[dict[str, Any]] = []
    for row in rows:
        tasks.append(
            {
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
            }
        )
    return tasks


# ── WebSocket 主循环 ─────────────────────────────────


async def _handle_client_message(
    websocket: WebSocket,
    log,
    trace_id: str,
    msg: dict[str, Any],
) -> None:
    msg_type = msg.get("type")
    if msg_type == "ping":
        await websocket.send_json({"type": "pong", "trace_id": trace_id})
    elif msg_type == "task.ack":
        log.bind(task_id=msg.get("task_id")).info("ws.operator.task_ack")


@router.websocket("/ws/operators/tasks")
async def operator_task_stream(websocket: WebSocket):
    operator_id = websocket.query_params.get("operator_id") or "anonymous"
    trace_id = websocket.query_params.get("trace_id") or f"ws-{operator_id}"
    log = logger.bind(
        trace_id=trace_id,
        component="ws",
        operator_id=operator_id,
        path="/ws/operators/tasks",
    )

    await websocket.accept()
    log.info("ws.operator.connected")
    await websocket.send_json(
        {
            "type": "connection.ready",
            "trace_id": trace_id,
            "operator_id": operator_id,
            "poll_interval_ms": int(POLL_INTERVAL_SECONDS * 1000),
        }
    )

    # 首次拉取并发送 snapshot
    try:
        initial_tasks = await _fetch_open_tasks()
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning("ws.operator.initial_fetch_failed")
        initial_tasks = []

    await websocket.send_json(
        {
            "type": "task.snapshot",
            "trace_id": trace_id,
            "tasks": initial_tasks,
        }
    )
    log.bind(task_count=len(initial_tasks)).info("ws.operator.snapshot_sent")
    state: dict[str, dict[str, Any]] = {t["task_id"]: t for t in initial_tasks}

    try:
        while True:
            # 非阻塞收客户端消息
            try:
                client_msg = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=CLIENT_RECV_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                client_msg = None
            if client_msg is not None:
                await _handle_client_message(websocket, log, trace_id, client_msg)

            # 拉最新任务、算 delta
            try:
                curr_tasks = await _fetch_open_tasks()
            except Exception as exc:
                log.bind(error_type=type(exc).__name__).warning("ws.operator.fetch_failed")
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            upserts, removed_ids = diff_tasks(state, curr_tasks)

            for task in upserts:
                await websocket.send_json(
                    {
                        "type": "task.upsert",
                        "trace_id": trace_id,
                        "task": task,
                    }
                )
            for tid in removed_ids:
                await websocket.send_json(
                    {
                        "type": "task.removed",
                        "trace_id": trace_id,
                        "task_id": tid,
                    }
                )

            if upserts or removed_ids:
                log.bind(
                    upsert_count=len(upserts),
                    removed_count=len(removed_ids),
                ).info("ws.operator.tasks_pushed")

            state = {t["task_id"]: t for t in curr_tasks}

            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        log.info("ws.operator.disconnected")
