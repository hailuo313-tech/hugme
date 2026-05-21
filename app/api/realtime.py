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

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel
from loguru import logger
from sqlalchemy import text

from core.database import AsyncSessionLocal
from services.ws_operator_task_delta import diff_tasks

router = APIRouter()

# ── WebSocket 连接管理器 (P2-11 + P4-02) ─────────────────────────────────

class PendingMessage:
    """待确认的消息，支持重推机制 (P4-02)。"""
    
    def __init__(
        self,
        message_id: str,
        message_type: str,
        payload: dict[str, Any],
        send_count: int = 0,
        last_sent_at: float | None = None,
    ):
        self.message_id = message_id
        self.message_type = message_type
        self.payload = payload
        self.send_count = send_count
        self.last_sent_at = last_sent_at
        self.acked = False

class ConnectionManager:
    """管理所有活跃的 WebSocket 连接，支持广播用户升级事件和 ACK 重推机制 (P4-02)。"""
    
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        # 每个连接的待确认消息: {websocket: {message_id: PendingMessage}}
        self.pending_messages: dict[WebSocket, dict[str, PendingMessage]] = {}
        # 重推配置
        self.max_retry_count = 3  # 最大重推次数
        self.retry_interval_seconds = 5.0  # 重推间隔（秒）
        self.message_timeout_seconds = 30.0  # 消息超时时间（秒）
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.pending_messages[websocket] = {}
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.pending_messages:
            del self.pending_messages[websocket]
    
    async def send_with_ack(
        self,
        websocket: WebSocket,
        message_type: str,
        payload: dict[str, Any],
        message_id: str | None = None,
    ) -> str:
        """发送消息并启动 ACK 跟踪 (P4-02)。
        
        Args:
            websocket: 目标 WebSocket 连接
            message_type: 消息类型（如 "task.upsert", "task.removed"）
            payload: 消息内容
            message_id: 可选的消息 ID，如不提供则自动生成
        
        Returns:
            消息 ID
        """
        if message_id is None:
            import uuid
            message_id = f"{message_type}-{uuid.uuid4().hex[:8]}"
        
        # 添加 message_id 到 payload
        payload_with_id = {**payload, "message_id": message_id}
        
        try:
            await websocket.send_json(payload_with_id)
            
            # 记录待确认消息
            import time
            pending_msg = PendingMessage(
                message_id=message_id,
                message_type=message_type,
                payload=payload_with_id,
                send_count=1,
                last_sent_at=time.time(),
            )
            self.pending_messages[websocket][message_id] = pending_msg
            
            logger.bind(
                component="ws",
                message_id=message_id,
                message_type=message_type,
            ).info("ws.message_sent_with_ack")
            
            return message_id
        except Exception as e:
            logger.bind(
                component="ws",
                message_id=message_id,
                error=str(e),
            ).error("ws.message_send_failed")
            raise
    
    async def handle_ack(self, websocket: WebSocket, message_id: str) -> bool:
        """处理客户端的 ACK 确认 (P4-02)。
        
        Args:
            websocket: WebSocket 连接
            message_id: 被确认的消息 ID
        
        Returns:
            是否成功确认（False 表示消息 ID 不存在或已确认）
        """
        if websocket not in self.pending_messages:
            return False
        
        pending = self.pending_messages[websocket].get(message_id)
        if not pending or pending.acked:
            return False
        
        pending.acked = True
        del self.pending_messages[websocket][message_id]
        
        logger.bind(
            component="ws",
            message_id=message_id,
            message_type=pending.message_type,
            send_count=pending.send_count,
        ).info("ws.message_acknowledged")
        
        return True
    
    async def retry_pending_messages(self, websocket: WebSocket) -> None:
        """重推待确认的消息 (P4-02)。
        
        对于超时未确认的消息，进行重推。超过最大重推次数则放弃。
        """
        import time
        
        if websocket not in self.pending_messages:
            return
        
        current_time = time.time()
        messages_to_retry = []
        message_ids_to_remove = []
        
        for message_id, pending in self.pending_messages[websocket].items():
            if pending.acked:
                message_ids_to_remove.append(message_id)
                continue
            
            # 检查是否需要重推
            time_since_send = current_time - (pending.last_sent_at or 0)
            if (
                time_since_send >= self.retry_interval_seconds
                and pending.send_count < self.max_retry_count
            ):
                messages_to_retry.append(pending)
            elif time_since_send >= self.message_timeout_seconds:
                # 超过超时时间，放弃重推
                logger.bind(
                    component="ws",
                    message_id=message_id,
                    message_type=pending.message_type,
                    send_count=pending.send_count,
                ).warning("ws.message_timeout_gave_up")
                message_ids_to_remove.append(message_id)
        
        # 执行重推
        for pending in messages_to_retry:
            try:
                await websocket.send_json(pending.payload)
                pending.send_count += 1
                pending.last_sent_at = current_time
                
                logger.bind(
                    component="ws",
                    message_id=pending.message_id,
                    message_type=pending.message_type,
                    send_count=pending.send_count,
                ).info("ws.message_retried")
            except Exception as e:
                logger.bind(
                    component="ws",
                    message_id=pending.message_id,
                    error=str(e),
                ).error("ws.message_retry_failed")
                message_ids_to_remove.append(pending.message_id)
        
        # 清理已确认或超时的消息
        for message_id in message_ids_to_remove:
            if message_id in self.pending_messages[websocket]:
                del self.pending_messages[websocket][message_id]
    
    async def broadcast_user_upgrade(self, upgrade_data: dict[str, Any]) -> None:
        """向所有连接的坐席广播用户升级事件 (P2-11)。"""
        if not self.active_connections:
            return
        
        disconnected = []
        for connection in self.active_connections:
            try:
                # 使用 send_with_ack 发送广播消息
                await self.send_with_ack(
                    connection,
                    "user.upgraded",
                    upgrade_data,
                )
            except Exception:
                disconnected.append(connection)
        
        # 清理断开的连接
        for conn in disconnected:
            self.disconnect(conn)
    
    async def broadcast(
        self,
        message_type: str,
        payload: dict[str, Any],
        message_id: str | None = None,
    ) -> dict[str, Any]:
        """通用广播方法，向所有连接发送消息 (P4-02)。
        
        Args:
            message_type: 消息类型
            payload: 消息内容
            message_id: 可选的消息 ID，如不提供则为每个连接生成独立的 ID
        
        Returns:
            广播统计信息：{total, success, failed, disconnected}
        """
        if not self.active_connections:
            return {
                "total": 0,
                "success": 0,
                "failed": 0,
                "disconnected": 0,
            }
        
        stats = {
            "total": len(self.active_connections),
            "success": 0,
            "failed": 0,
            "disconnected": 0,
        }
        
        disconnected = []
        for connection in self.active_connections:
            try:
                # 使用 send_with_ack 发送广播消息
                await self.send_with_ack(
                    connection,
                    message_type,
                    payload,
                    message_id,  # 如果为 None，send_with_ack 会生成独立 ID
                )
                stats["success"] += 1
            except Exception:
                stats["failed"] += 1
                disconnected.append(connection)
        
        # 清理断开的连接
        for conn in disconnected:
            self.disconnect(conn)
            stats["disconnected"] += 1
        
        logger.bind(
            component="ws",
            message_type=message_type,
            stats=stats,
        ).info("ws.broadcast_completed")
        
        return stats
    
    async def get_pending_message_count(self, websocket: WebSocket) -> int:
        """获取指定连接的待确认消息数量 (P4-02)。
        
        Args:
            websocket: WebSocket 连接
        
        Returns:
            待确认消息数量
        """
        if websocket not in self.pending_messages:
            return 0
        return len(self.pending_messages[websocket])
    
    async def get_connection_stats(self) -> dict[str, Any]:
        """获取连接管理器的统计信息 (P4-02)。
        
        Returns:
            统计信息字典
        """
        total_pending = sum(
            len(pending)
            for pending in self.pending_messages.values()
        )
        
        return {
            "active_connections": len(self.active_connections),
            "total_pending_messages": total_pending,
            "max_retry_count": self.max_retry_count,
            "retry_interval_seconds": self.retry_interval_seconds,
            "message_timeout_seconds": self.message_timeout_seconds,
        }

# 全局连接管理器实例
manager = ConnectionManager()

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
        ).mappings().all()

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


# ── 用户升级事件推送 (P2-11) ────────────────────────────────


async def notify_user_upgrade(
    user_id: str,
    previous_level: str,
    new_level: str,
    reason: str = "manual_recalculation",
) -> None:
    """向所有连接的坐席广播用户升级事件 (P2-11)。
    
    Args:
        user_id: 升级的用户ID
        previous_level: 升级前的等级 (S/A/B/C/D)
        new_level: 升级后的等级 (S/A/B/C/D)
        reason: 升级原因 (payment_completed, manual_recalculation, etc.)
    """
    trace_id = f"upgrade-{user_id}"
    log = logger.bind(
        trace_id=trace_id,
        component="ws",
        user_id=user_id,
        previous_level=previous_level,
        new_level=new_level,
        reason=reason,
    )
    
    upgrade_event = {
        "type": "user.upgraded",
        "trace_id": trace_id,
        "user_id": user_id,
        "previous_level": previous_level,
        "new_level": new_level,
        "reason": reason,
        "upgraded_at": datetime.now().isoformat(),
    }
    
    await manager.broadcast_user_upgrade(upgrade_event)
    log.info("ws.user_upgrade_broadcasted")


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
        # P4-02: 处理任务确认（兼容旧的 task_id 字段）
        task_id = msg.get("task_id")
        message_id = msg.get("message_id")
        
        if message_id:
            # 新的 ACK 机制：使用 message_id
            success = await manager.handle_ack(websocket, message_id)
            if success:
                log.bind(message_id=message_id).info("ws.operator.message_ack")
            else:
                log.bind(message_id=message_id).warning("ws.operator.message_ack_not_found")
        elif task_id:
            # 兼容旧的 ACK 机制：使用 task_id
            log.bind(task_id=task_id).info("ws.operator.task_ack")
    elif msg_type == "message.ack":
        # P4-02: 新的通用消息确认机制
        message_id = msg.get("message_id")
        if message_id:
            success = await manager.handle_ack(websocket, message_id)
            if success:
                log.bind(message_id=message_id).info("ws.operator.message_ack")
            else:
                log.bind(message_id=message_id).warning("ws.operator.message_ack_not_found")


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

    await manager.connect(websocket)
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
        log.bind(error_type=type(exc).__name__).warning(
            "ws.operator.initial_fetch_failed"
        )
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
        retry_counter = 0
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

            # P4-02: 定期重推待确认的消息（每 5 秒检查一次）
            retry_counter += 1
            if retry_counter >= int(manager.retry_interval_seconds / POLL_INTERVAL_SECONDS):
                await manager.retry_pending_messages(websocket)
                retry_counter = 0

            # 拉最新任务、算 delta
            try:
                curr_tasks = await _fetch_open_tasks()
            except Exception as exc:
                log.bind(error_type=type(exc).__name__).warning(
                    "ws.operator.fetch_failed"
                )
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            upserts, removed_ids = diff_tasks(state, curr_tasks)

            # P4-02: 使用 send_with_ack 发送任务更新消息
            for task in upserts:
                await manager.send_with_ack(
                    websocket,
                    "task.upsert",
                    {
                        "type": "task.upsert",
                        "trace_id": trace_id,
                        "task": task,
                    },
                )
            for tid in removed_ids:
                await manager.send_with_ack(
                    websocket,
                    "task.removed",
                    {
                        "type": "task.removed",
                        "trace_id": trace_id,
                        "task_id": tid,
                    },
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
    finally:
        manager.disconnect(websocket)


# ── 测试端点 (P2-11) ────────────────────────────────────────


class UserUpgradeTest(BaseModel):
    user_id: str
    previous_level: str
    new_level: str
    reason: str = "test"


@router.post("/test/user-upgrade")
async def test_user_upgrade(data: UserUpgradeTest):
    """测试端点：触发用户升级事件广播 (P2-11)。
    
    仅用于开发/测试环境，生产环境应移除此端点。
    """
    # 验证等级值
    valid_levels = {"S", "A", "B", "C", "D"}
    if data.previous_level not in valid_levels:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid previous_level: {data.previous_level}. Must be one of {valid_levels}"
        )
    if data.new_level not in valid_levels:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid new_level: {data.new_level}. Must be one of {valid_levels}"
        )
    
    await notify_user_upgrade(
        user_id=data.user_id,
        previous_level=data.previous_level,
        new_level=data.new_level,
        reason=data.reason,
    )
    
    return {
        "status": "success",
        "message": "User upgrade event broadcasted to all connected operators",
        "user_id": data.user_id,
        "previous_level": data.previous_level,
        "new_level": data.new_level,
    }


# ── P4-02: 通用广播测试端点 ────────────────────────────────────────


class BroadcastTest(BaseModel):
    message_type: str
    payload: dict[str, Any]


@router.post("/test/broadcast")
async def test_broadcast(data: BroadcastTest):
    """测试端点：通用广播功能 (P4-02)。
    
    仅用于开发/测试环境，生产环境应移除此端点。
    """
    stats = await manager.broadcast(
        message_type=data.message_type,
        payload=data.payload,
    )
    
    return {
        "status": "success",
        "message": f"Broadcast {data.message_type} to all connected operators",
        "stats": stats,
    }


@router.get("/test/stats")
async def test_stats():
    """测试端点：获取连接管理器统计信息 (P4-02)。
    
    仅用于开发/测试环境，生产环境应移除此端点。
    """
    return await manager.get_connection_stats()


# ── P1-07: 通用 WebSocket 端点 (ping/pong) ─────────────────────

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    P1-07: 通用 WebSocket 端点，支持 ping/pong 功能
    
    浏览器可连接 /ws 端点并发送 ping 消息，服务器将回复 pong
    """
    client_id = websocket.query_params.get("client_id") or "anonymous"
    trace_id = websocket.query_params.get("trace_id") or f"ws-{client_id}"
    
    log = logger.bind(
        trace_id=trace_id,
        component="ws",
        client_id=client_id,
        path="/ws",
    )
    
    await manager.connect(websocket)
    log.info("ws.client.connected")
    
    # 发送连接就绪消息
    await websocket.send_json({
        "type": "connection.ready",
        "trace_id": trace_id,
        "client_id": client_id,
        "server_time": datetime.now().isoformat(),
    })
    
    try:
        while True:
            # 非阻塞接收客户端消息
            try:
                client_msg = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=CLIENT_RECV_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                client_msg = None
            
            if client_msg is not None:
                msg_type = client_msg.get("type")
                
                if msg_type == "ping":
                    # P1-07: ping/pong 功能
                    await websocket.send_json({
                        "type": "pong",
                        "trace_id": trace_id,
                        "client_id": client_id,
                        "server_time": datetime.now().isoformat(),
                    })
                    log.info("ws.client.ping_pong")
                elif msg_type == "echo":
                    # 回显功能用于测试
                    await websocket.send_json({
                        "type": "echo.response",
                        "trace_id": trace_id,
                        "original_message": client_msg,
                    })
                    log.bind(original_message=client_msg).info("ws.client.echo")
                else:
                    log.bind(msg_type=msg_type).warning("ws.client.unknown_message_type")
    
    except WebSocketDisconnect:
        log.info("ws.client.disconnected")
    except Exception as e:
        log.bind(error=str(e)).error("ws.client.error")
    finally:
        manager.disconnect(websocket)
