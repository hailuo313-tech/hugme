# P4-02: WebSocket 服务端广播 + ACK 重推机制

> **状态**: ✅ 已完成  
> **验收标准**: conformance 测试通过  
> **实现日期**: 2026-05-21

## 概述

本任务在现有的 WebSocket 协议基础上实现了可靠的消息传递机制，包括：
1. **ACK 确认机制**：客户端可以确认收到服务器消息
2. **自动重推**：未确认的消息会自动重推，确保消息可靠传递
3. **通用广播**：扩展了服务端广播功能，支持任意类型消息的广播

## 实现内容

### 1. ACK 确认机制

#### 新增数据结构
- `PendingMessage`：跟踪待确认消息的状态
  - `message_id`：消息唯一标识
  - `message_type`：消息类型
  - `payload`：消息内容
  - `send_count`：发送次数
  - `last_sent_at`：最后发送时间
  - `acked`：是否已确认

#### ConnectionManager 扩展
- `pending_messages`：跟踪每个连接的待确认消息
- `send_with_ack()`：发送消息并启动 ACK 跟踪
- `handle_ack()`：处理客户端 ACK 确认
- `retry_pending_messages()`：重推待确认消息

#### 配置参数
- `max_retry_count = 3`：最大重推次数
- `retry_interval_seconds = 5.0`：重推间隔（秒）
- `message_timeout_seconds = 30.0`：消息超时时间（秒）

### 2. 客户端协议扩展

#### 新增客户端事件
```json
{
  "type": "message.ack",
  "message_id": "task.upsert-a1b2c3d4"
}
```

#### 服务器消息变更
所有服务器消息（除 `connection.ready`, `task.snapshot`, `pong` 外）现在包含 `message_id` 字段：
```json
{
  "type": "task.upsert",
  "trace_id": "ws-op-1",
  "message_id": "task.upsert-a1b2c3d4",
  "task": {...}
}
```

### 3. 通用广播功能

#### 新增方法
- `broadcast()`：通用广播方法，支持任意类型消息
- `get_pending_message_count()`：获取指定连接的待确认消息数量
- `get_connection_stats()`：获取连接管理器统计信息

#### 测试端点
- `POST /test/broadcast`：测试通用广播功能
- `GET /test/stats`：获取连接统计信息

### 4. 兼容性

- 保留对旧的 `task.ack` 的支持
- 新的 `message.ack` 是推荐方式
- 广播消息（如 `user.upgraded`）也支持 ACK 重推机制

## 文件变更

### 修改的文件
- `app/api/realtime.py`：核心实现
  - 新增 `PendingMessage` 类
  - 扩展 `ConnectionManager` 类
  - 更新 WebSocket 主循环集成 ACK 重推
  - 新增测试端点

- `app/services/ws_protocol_conformance.py`：协议一致性
  - 添加 `message.ack` 客户端事件类型
  - 更新验证逻辑

- `tests/test_c09_ws_protocol.py`：协议测试
  - 更新客户端事件类型测试
  - 添加客户端事件数量测试

- `fixtures/c09_ws_protocol.json`：测试数据
  - 添加 `message.ack` 测试用例

- `docs/ws_protocol.md`：协议文档
  - 添加 P4-02 ACK 重推机制说明

### 新增的文件
- `tests/test_p4_02_ack_retry.py`：ACK 重推机制单元测试

## 测试覆盖

### 单元测试 (`test_p4_02_ack_retry.py`)
- ✅ PendingMessage 对象创建
- ✅ 连接管理器的连接和断开
- ✅ 带 ACK 的消息发送
- ✅ 成功的 ACK 处理
- ✅ 处理不存在的消息 ID
- ✅ 重复确认同一消息
- ✅ 消息重推机制
- ✅ 超过最大重推次数
- ✅ 消息超时处理
- ✅ WebSocket 发送失败处理
- ✅ 连接管理器配置
- ✅ 通用广播功能
- ✅ 多连接广播
- ✅ 广播失败处理
- ✅ 待确认消息数量查询
- ✅ 连接统计信息

### 协议一致性测试
- ✅ 客户端事件类型验证
- ✅ 服务器事件类型验证
- ✅ 消息格式验证
- ✅ 实现契约一致性

## 使用示例

### 服务器端
```python
# 发送需要确认的消息
message_id = await manager.send_with_ack(
    websocket,
    "task.upsert",
    {
        "type": "task.upsert",
        "trace_id": trace_id,
        "task": task_data,
    }
)

# 广播消息到所有连接
stats = await manager.broadcast(
    "system.announcement",
    {"message": "System maintenance in 10 minutes"},
)

# 获取连接统计
stats = await manager.get_connection_stats()
```

### 客户端
```javascript
// 接收服务器消息
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  // 处理业务逻辑
  if (data.type === 'task.upsert') {
    handleTaskUpdate(data.task);
  }
  
  // 发送 ACK 确认
  if (data.message_id) {
    ws.send(JSON.stringify({
      type: 'message.ack',
      message_id: data.message_id
    }));
  }
};
```

## 验收标准

- ✅ conformance 测试通过
- ✅ 单元测试覆盖所有核心功能
- ✅ 协议文档更新
- ✅ 向后兼容旧的 `task.ack` 机制
- ✅ 日志记录完整

## 部署注意事项

1. **环境变量**：无需新增环境变量，使用默认配置
2. **数据库变更**：无数据库变更
3. **向后兼容**：完全兼容现有客户端，`message.ack` 为可选功能
4. **性能影响**：每个连接增加少量内存用于跟踪待确认消息
5. **监控建议**：关注 `ws.message_timeout_gave_up` 日志，可能指示网络问题

## 后续优化建议

1. **配置化**：将重推参数移至配置文件，支持运行时调整
2. **监控指标**：添加 Prometheus 指标，跟踪 ACK 率、重推率等
3. **批量 ACK**：支持批量确认多个消息，减少网络开销
4. **持久化**：对于关键消息，考虑持久化到 Redis，支持跨实例重推
5. **退避策略**：实现指数退避算法，避免网络拥塞时频繁重推

## 相关文档

- [WebSocket 协议规范](ws_protocol.md)
- [D5-4 WebSocket Task Push Protocol](../D5-4_WEBSOCKET_PROTOCOL.md)
- [C-09 检查报告](C09_INSPECTION_REPORT.md)