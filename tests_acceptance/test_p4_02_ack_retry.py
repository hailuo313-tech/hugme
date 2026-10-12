"""P4-02: ACK 重推机制单元测试"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.realtime import ConnectionManager, PendingMessage


@pytest.fixture
def manager():
    """创建 ConnectionManager 实例用于测试"""
    return ConnectionManager()


@pytest.fixture
def mock_websocket():
    """创建模拟的 WebSocket 连接"""
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


def test_pending_message_creation():
    """测试 PendingMessage 对象创建"""
    msg = PendingMessage(
        message_id="test-msg-1",
        message_type="task.upsert",
        payload={"type": "task.upsert", "task": {"task_id": "t1"}},
        send_count=1,
        last_sent_at=time.time(),
    )
    
    assert msg.message_id == "test-msg-1"
    assert msg.message_type == "task.upsert"
    assert msg.send_count == 1
    assert msg.acked is False


def test_manager_connect_disconnect(manager, mock_websocket):
    """测试连接管理器的连接和断开"""
    # 测试连接
    asyncio.run(manager.connect(mock_websocket))
    assert mock_websocket in manager.active_connections
    assert mock_websocket in manager.pending_messages
    
    # 测试断开
    manager.disconnect(mock_websocket)
    assert mock_websocket not in manager.active_connections
    assert mock_websocket not in manager.pending_messages


async def test_send_with_ack(manager, mock_websocket):
    """测试带 ACK 的消息发送"""
    await manager.connect(mock_websocket)
    
    payload = {
        "type": "task.upsert",
        "trace_id": "ws-test",
        "task": {"task_id": "t1"},
    }
    
    message_id = await manager.send_with_ack(
        mock_websocket,
        "task.upsert",
        payload,
    )
    
    # 验证消息已发送
    mock_websocket.send_json.assert_called_once()
    sent_data = mock_websocket.send_json.call_args[0][0]
    
    # 验证 message_id 已添加
    assert "message_id" in sent_data
    assert sent_data["message_id"] == message_id
    
    # 验证消息已记录为待确认
    assert message_id in manager.pending_messages[mock_websocket]
    pending = manager.pending_messages[mock_websocket][message_id]
    assert pending.acked is False
    assert pending.send_count == 1


async def test_handle_ack_success(manager, mock_websocket):
    """测试成功的 ACK 处理"""
    await manager.connect(mock_websocket)
    
    # 先发送一条消息
    message_id = await manager.send_with_ack(
        mock_websocket,
        "task.upsert",
        {"type": "task.upsert", "task": {"task_id": "t1"}},
    )
    
    # 确认消息在待确认列表中
    assert message_id in manager.pending_messages[mock_websocket]
    
    # 处理 ACK
    success = await manager.handle_ack(mock_websocket, message_id)
    
    # 验证 ACK 成功
    assert success is True
    assert message_id not in manager.pending_messages[mock_websocket]


async def test_handle_ack_not_found(manager, mock_websocket):
    """测试处理不存在的消息 ID"""
    await manager.connect(mock_websocket)
    
    # 尝试确认不存在的消息
    success = await manager.handle_ack(mock_websocket, "non-existent-id")
    
    # 验证返回 False
    assert success is False


async def test_handle_ack_already_acked(manager, mock_websocket):
    """测试重复确认同一消息"""
    await manager.connect(mock_websocket)
    
    # 发送消息
    message_id = await manager.send_with_ack(
        mock_websocket,
        "task.upsert",
        {"type": "task.upsert", "task": {"task_id": "t1"}},
    )
    
    # 第一次确认
    success1 = await manager.handle_ack(mock_websocket, message_id)
    assert success1 is True
    
    # 第二次确认（应该失败）
    success2 = await manager.handle_ack(mock_websocket, message_id)
    assert success2 is False


async def test_retry_pending_messages_no_retry(manager, mock_websocket):
    """测试没有需要重推的消息"""
    await manager.connect(mock_websocket)
    
    # 发送消息并立即确认
    message_id = await manager.send_with_ack(
        mock_websocket,
        "task.upsert",
        {"type": "task.upsert", "task": {"task_id": "t1"}},
    )
    await manager.handle_ack(mock_websocket, message_id)
    
    # 尝试重推（应该没有动作）
    await manager.retry_pending_messages(mock_websocket)
    
    # 验证没有重发消息
    assert mock_websocket.send_json.call_count == 1  # 只有最初的发送


async def test_retry_pending_messages_with_retry(manager, mock_websocket):
    """测试消息重推"""
    await manager.connect(mock_websocket)
    
    # 设置较短的重推间隔用于测试
    manager.retry_interval_seconds = 0.1
    
    # 发送消息但不确认
    message_id = await manager.send_with_ack(
        mock_websocket,
        "task.upsert",
        {"type": "task.upsert", "task": {"task_id": "t1"}},
    )
    
    # 等待超过重推间隔
    await asyncio.sleep(0.15)
    
    # 执行重推
    await manager.retry_pending_messages(mock_websocket)
    
    # 验证消息被重发（总共 2 次：初始发送 + 重推）
    assert mock_websocket.send_json.call_count == 2
    
    # 验证 send_count 增加
    pending = manager.pending_messages[mock_websocket][message_id]
    assert pending.send_count == 2


async def test_retry_max_count_exceeded(manager, mock_websocket):
    """测试超过最大重推次数后放弃"""
    await manager.connect(mock_websocket)
    
    # 设置较短的重推间隔和较小的最大重推次数
    manager.retry_interval_seconds = 0.1
    manager.max_retry_count = 1
    
    # 发送消息
    message_id = await manager.send_with_ack(
        mock_websocket,
        "task.upsert",
        {"type": "task.upsert", "task": {"task_id": "t1"}},
    )
    
    # 等待超过重推间隔
    await asyncio.sleep(0.15)
    
    # 第一次重推
    await manager.retry_pending_messages(mock_websocket)
    assert mock_websocket.send_json.call_count == 2
    
    # 再次等待
    await asyncio.sleep(0.15)
    
    # 第二次重推（应该被放弃，因为已达到最大重推次数）
    await manager.retry_pending_messages(mock_websocket)
    assert mock_websocket.send_json.call_count == 2  # 没有新的重发
    
    # 验证消息已从待确认列表中移除
    assert message_id not in manager.pending_messages[mock_websocket]


async def test_message_timeout(manager, mock_websocket):
    """测试消息超时"""
    await manager.connect(mock_websocket)
    
    # 设置较短的超时时间
    manager.message_timeout_seconds = 0.2
    manager.retry_interval_seconds = 0.1
    manager.max_retry_count = 10  # 设置很大的重推次数，确保是超时而不是重推次数限制
    
    # 发送消息
    message_id = await manager.send_with_ack(
        mock_websocket,
        "task.upsert",
        {"type": "task.upsert", "task": {"task_id": "t1"}},
    )
    
    # 等待超过超时时间
    await asyncio.sleep(0.25)
    
    # 执行重推（应该因为超时而放弃）
    await manager.retry_pending_messages(mock_websocket)
    
    # 验证消息已从待确认列表中移除
    assert message_id not in manager.pending_messages[mock_websocket]


async def test_retry_on_websocket_error(manager, mock_websocket):
    """测试 WebSocket 发送失败时的处理"""
    await manager.connect(mock_websocket)
    
    # 设置发送失败
    
    # 设置较短的重推间隔
    manager.retry_interval_seconds = 0.1
    
    # 发送消息
    message_id = await manager.send_with_ack(
        mock_websocket,
        "task.upsert",
        {"type": "task.upsert", "task": {"task_id": "t1"}},
    )
    mock_websocket.send_json.side_effect = Exception("Connection lost")
    
    # 等待超过重推间隔
    await asyncio.sleep(0.15)
    
    # 执行重推（应该失败并清理消息）
    await manager.retry_pending_messages(mock_websocket)
    
    # 验证消息已从待确认列表中移除（因为重推失败）
    assert message_id not in manager.pending_messages[mock_websocket]


def test_manager_configuration():
    """测试连接管理器的配置"""
    manager = ConnectionManager()
    
    assert manager.max_retry_count == 3
    assert manager.retry_interval_seconds == 5.0
    assert manager.message_timeout_seconds == 30.0


async def test_broadcast_no_connections(manager):
    """测试没有连接时的广播"""
    stats = await manager.broadcast(
        "test.message",
        {"data": "test"},
    )
    
    assert stats["total"] == 0
    assert stats["success"] == 0
    assert stats["failed"] == 0


async def test_broadcast_with_connections(manager, mock_websocket):
    """测试有连接时的广播"""
    await manager.connect(mock_websocket)
    
    stats = await manager.broadcast(
        "test.message",
        {"data": "test"},
    )
    
    assert stats["total"] == 1
    assert stats["success"] == 1
    assert stats["failed"] == 0
    
    # 验证消息已发送
    mock_websocket.send_json.assert_called_once()


async def test_broadcast_with_multiple_connections(manager):
    """测试向多个连接广播"""
    # 创建多个模拟连接
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    ws3 = AsyncMock()
    
    await manager.connect(ws1)
    await manager.connect(ws2)
    await manager.connect(ws3)
    
    stats = await manager.broadcast(
        "test.message",
        {"data": "test"},
    )
    
    assert stats["total"] == 3
    assert stats["success"] == 3
    assert stats["failed"] == 0
    
    # 验证所有连接都收到了消息
    assert ws1.send_json.called
    assert ws2.send_json.called
    assert ws3.send_json.called


async def test_broadcast_with_failed_connection(manager, mock_websocket):
    """测试广播时处理失败的连接"""
    await manager.connect(mock_websocket)
    
    # 设置发送失败
    mock_websocket.send_json.side_effect = Exception("Connection error")
    
    stats = await manager.broadcast(
        "test.message",
        {"data": "test"},
    )
    
    assert stats["total"] == 1
    assert stats["success"] == 0
    assert stats["failed"] == 1
    assert stats["disconnected"] == 1
    
    # 验证失败的连接已被清理
    assert mock_websocket not in manager.active_connections


async def test_get_pending_message_count(manager, mock_websocket):
    """测试获取待确认消息数量"""
    await manager.connect(mock_websocket)
    
    # 初始应该为 0
    count = await manager.get_pending_message_count(mock_websocket)
    assert count == 0
    
    # 发送几条消息
    await manager.send_with_ack(mock_websocket, "test.type", {"data": "test1"})
    await manager.send_with_ack(mock_websocket, "test.type", {"data": "test2"})
    
    # 应该有 2 条待确认消息
    count = await manager.get_pending_message_count(mock_websocket)
    assert count == 2


async def test_get_connection_stats(manager, mock_websocket):
    """测试获取连接统计信息"""
    await manager.connect(mock_websocket)
    
    # 发送几条消息
    await manager.send_with_ack(mock_websocket, "test.type", {"data": "test1"})
    await manager.send_with_ack(mock_websocket, "test.type", {"data": "test2"})
    
    stats = await manager.get_connection_stats()
    
    assert stats["active_connections"] == 1
    assert stats["total_pending_messages"] == 2
    assert stats["max_retry_count"] == 3
    assert stats["retry_interval_seconds"] == 5.0
    assert stats["message_timeout_seconds"] == 30.0
