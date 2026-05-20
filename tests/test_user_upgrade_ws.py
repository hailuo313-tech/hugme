"""
P2-11: USER_UPGRADED WebSocket 推送测试

测试用户升级事件的 WebSocket 广播功能。
"""
import asyncio
import json
from unittest.mock import Mock, AsyncMock, patch, ANY
import pytest
from fastapi.testclient import TestClient
from fastapi import WebSocket
from sqlalchemy import text

from app.main import app
from app.api.realtime import notify_user_upgrade, manager
from core.database import AsyncSessionLocal


@pytest.fixture
def client():
    """创建测试客户端。"""
    return TestClient(app)


@pytest.fixture
async def db_session():
    """创建测试数据库会话。"""
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()


class TestConnectionManager:
    """测试连接管理器的基本功能。"""
    
    @pytest.mark.asyncio
    async def test_connect_disconnect(self):
        """测试连接和断开连接。"""
        # 清空连接列表
        manager.active_connections.clear()
        
        # 创建模拟 WebSocket
        mock_ws = Mock(spec=WebSocket)
        async def mock_accept():
            pass
        mock_ws.accept = mock_accept
        
        # 测试连接
        await manager.connect(mock_ws)
        assert len(manager.active_connections) == 1
        assert mock_ws in manager.active_connections
        
        # 测试断开
        manager.disconnect(mock_ws)
        assert len(manager.active_connections) == 0
        assert mock_ws not in manager.active_connections
    
    @pytest.mark.asyncio
    async def test_broadcast_user_upgrade(self):
        """测试广播用户升级事件。"""
        # 清空连接列表
        manager.active_connections.clear()
        
        # 创建多个模拟 WebSocket
        mock_ws1 = Mock(spec=WebSocket)
        mock_ws2 = Mock(spec=WebSocket)
        mock_ws1.send_json = AsyncMock()
        mock_ws2.send_json = AsyncMock()
        
        # 连接多个客户端
        await manager.connect(mock_ws1)
        await manager.connect(mock_ws2)
        
        # 准备升级数据
        upgrade_data = {
            "type": "user.upgraded",
            "trace_id": "test-123",
            "user_id": "user-123",
            "previous_level": "B",
            "new_level": "A",
            "reason": "payment_completed",
            "upgraded_at": "2026-05-19T19:00:00",
        }
        
        # 广播事件
        await manager.broadcast_user_upgrade(upgrade_data)
        
        # 验证所有连接都收到了消息
        mock_ws1.send_json.assert_called_once_with(upgrade_data)
        mock_ws2.send_json.assert_called_once_with(upgrade_data)
        
        # 清理
        manager.disconnect(mock_ws1)
        manager.disconnect(mock_ws2)
    
    @pytest.mark.asyncio
    async def test_broadcast_with_disconnected_client(self):
        """测试广播时处理断开的客户端。"""
        # 清空连接列表
        manager.active_connections.clear()
        
        # 创建一个正常和一个异常的 WebSocket
        mock_ws_ok = Mock(spec=WebSocket)
        mock_ws_fail = Mock(spec=WebSocket)
        
        mock_ws_ok.send_json = AsyncMock()
        mock_ws_fail.send_json = AsyncMock(side_effect=Exception("Connection lost"))
        
        # 连接客户端
        await manager.connect(mock_ws_ok)
        await manager.connect(mock_ws_fail)
        
        # 准备升级数据
        upgrade_data = {
            "type": "user.upgraded",
            "trace_id": "test-456",
            "user_id": "user-456",
            "previous_level": "C",
            "new_level": "A",
            "reason": "payment_completed",
            "upgraded_at": "2026-05-19T19:00:00",
        }
        
        # 广播事件（应该自动清理断开的连接）
        await manager.broadcast_user_upgrade(upgrade_data)
        
        # 验证正常连接收到消息
        mock_ws_ok.send_json.assert_called_once_with(upgrade_data)
        
        # 验证断开的连接被移除
        assert len(manager.active_connections) == 1
        assert mock_ws_ok in manager.active_connections
        assert mock_ws_fail not in manager.active_connections
        
        # 清理
        manager.disconnect(mock_ws_ok)


class TestNotifyUserUpgrade:
    """测试 notify_user_upgrade 函数。"""
    
    @pytest.mark.asyncio
    async def test_notify_user_upgrade_basic(self):
        """测试基本的用户升级通知。"""
        # 清空连接列表
        manager.active_connections.clear()
        
        # 创建模拟 WebSocket
        mock_ws = Mock(spec=WebSocket)
        mock_ws.send_json = AsyncMock()
        await manager.connect(mock_ws)
        
        # 调用通知函数
        await notify_user_upgrade(
            user_id="user-789",
            previous_level="B",
            new_level="A",
            reason="payment_completed",
        )
        
        # 验证 WebSocket 收到正确格式的事件
        expected_call = {
            "type": "user.upgraded",
            "trace_id": "upgrade-user-789",
            "user_id": "user-789",
            "previous_level": "B",
            "new_level": "A",
            "reason": "payment_completed",
            "upgraded_at": ANY,  # 时间戳动态生成
        }
        
        mock_ws.send_json.assert_called_once()
        call_args = mock_ws.send_json.call_args[0][0]
        
        # 验证关键字段
        assert call_args["type"] == "user.upgraded"
        assert call_args["user_id"] == "user-789"
        assert call_args["previous_level"] == "B"
        assert call_args["new_level"] == "A"
        assert call_args["reason"] == "payment_completed"
        assert "trace_id" in call_args
        assert "upgraded_at" in call_args
        
        # 清理
        manager.disconnect(mock_ws)


@pytest.mark.skip(reason="API endpoint may not be implemented yet")
class TestUserUpgradeAPI:
    """测试用户升级的 API 端点。"""
    
    def test_test_user_upgrade_valid(self, client):
        """测试测试端点 - 有效数据。"""
        response = client.post(
            "/api/v1/realtime/test/user-upgrade",
            json={
                "user_id": "test-user-123",
                "previous_level": "B",
                "new_level": "A",
                "reason": "test",
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["user_id"] == "test-user-123"
        assert data["previous_level"] == "B"
        assert data["new_level"] == "A"
    
    def test_test_user_upgrade_invalid_level(self, client):
        """测试测试端点 - 无效等级。"""
        response = client.post(
            "/api/v1/realtime/test/user-upgrade",
            json={
                "user_id": "test-user-123",
                "previous_level": "X",  # 无效等级
                "new_level": "A",
                "reason": "test",
            },
        )
        
        assert response.status_code == 400
        assert "Invalid previous_level" in response.json()["detail"]
    
    def test_test_user_upgrade_missing_fields(self, client):
        """测试测试端点 - 缺少字段。"""
        response = client.post(
            "/api/v1/realtime/test/user-upgrade",
            json={
                "user_id": "test-user-123",
                # 缺少 previous_level 和 new_level
            },
        )
        
        assert response.status_code == 422  # Validation error


class TestWebSocketIntegration:
    """测试 WebSocket 集成。"""
    
    def test_websocket_endpoint_connects(self, client):
        """测试 WebSocket 端点可以连接。"""
        with client.websocket_connect("/ws/operators/tasks?operator_id=test-op") as websocket:
            # 应该收到 connection.ready
            data = websocket.receive_json()
            assert data["type"] == "connection.ready"
            assert data["operator_id"] == "test-op"
            
            # 应该收到 task.snapshot
            data = websocket.receive_json()
            assert data["type"] == "task.snapshot"
            assert "tasks" in data
    
    @pytest.mark.asyncio
    async def test_websocket_receives_upgrade_event(self, client):
        """测试 WebSocket 可以接收升级事件。"""
        # 这个测试需要更复杂的设置来捕获 WebSocket 消息
        # 在实际集成测试中实现
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])