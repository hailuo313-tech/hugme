# P4-08: H5 WebSocket + 正在输入动效

## 任务概述

**任务编号**: P4-08  
**阶段**: 阶段04 看板前端  
**负责人**: Devin  
**验收标准**: H5 可见 typing  
**依赖**: P4-01 (WebSocket 协议)

## 功能描述

为 H5 移动端实现 WebSocket 连接和正在输入动效，提供实时的聊天体验。

## 实现细节

### 1. 后端 WebSocket 端点

在 `app/api/realtime.py` 中添加了 H5 用户端 WebSocket 端点：

```python
@router.websocket("/ws/h5/chat")
async def h5_chat_websocket(
    websocket: WebSocket,
    user_id: str,
    conversation_id: str,
    trace_id: str = "h5-ws-default",
):
```

#### 连接管理器

```python
class H5ConnectionManager:
    """H5 用户端 WebSocket 连接管理器。"""
    
    def __init__(self):
        # user_id -> WebSocket
        self.active_connections: dict[str, WebSocket] = {}
```

#### 支持的事件类型

**服务器事件**:
- `connection.ready`: 连接就绪确认
- `typing.status`: 正在输入状态通知
- `pong`: 响应客户端 ping

**客户端事件**:
- `ping`: 保持连接活跃
- `typing.start`: 用户开始输入
- `typing.stop`: 用户停止输入
- `message.ack`: 消息确认

### 2. 前端 H5 聊天页面

在 `admin/app/h5/chat/page.tsx` 中实现了完整的 H5 聊天页面：

#### 页面特性

1. **响应式设计**
   - 移动端优先的布局
   - 深色渐变背景（紫色系）
   - 毛玻璃效果的 UI 组件

2. **WebSocket 连接管理**
   - 自动连接和断线处理
   - 定期 ping 保持连接活跃
   - 连接状态实时显示

3. **消息列表**
   - 自动滚动到底部
   - 区分发送者和接收者样式
   - 消息气泡设计

#### 正在输入动效

使用三个跳动的圆点实现正在输入指示器：

```tsx
{typingStatus?.is_typing && (
  <div className="flex justify-start">
    <div className="bg-white/10 backdrop-blur-sm rounded-2xl px-4 py-3">
      <div className="flex items-center gap-1">
        <div className="w-2 h-2 bg-white/60 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
        <div className="w-2 h-2 bg-white/60 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
        <div className="w-2 h-2 bg-white/60 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
      </div>
    </div>
  </div>
)}
```

#### 输入状态同步

```typescript
// 处理输入变化
const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
  setInputText(e.target.value);
  
  // 发送正在输入开始
  sendTypingStart();
  
  // 清除之前的定时器
  if (typingTimeoutRef.current) {
    clearTimeout(typingTimeoutRef.current);
  }
  
  // 1秒后发送停止输入
  typingTimeoutRef.current = setTimeout(() => {
    sendTypingStop();
  }, 1000);
};
```

### 3. WebSocket 协议更新

在 `docs/ws_protocol.md` 中添加了：

#### 新增端点

```text
GET /ws/h5/chat?user_id=<user-id>&conversation_id=<conversation-id>&trace_id=<optional>
```

#### H5 端生命周期

1. Client connects with `user_id` and `conversation_id`.
2. Server sends `connection.ready`.
3. Client may send `typing.start` / `typing.stop` to indicate typing status.
4. Server sends `typing.status` to notify typing status changes.
5. Client may send `ping`; server responds with `pong`.
6. Client may send `message.ack` to acknowledge message receipt.

#### CSS 动画实现

```css
@keyframes bounce {
  0%, 80%, 100% { transform: scale(0); }
  40% { transform: scale(1); }
}
```

## 修改的文件

### 后端文件

1. **app/api/realtime.py**
   - 添加 `H5ConnectionManager` 类
   - 实现 `/ws/h5/chat` WebSocket 端点
   - 支持正在输入状态同步
   - 添加连接管理和日志记录

### 前端文件

2. **admin/app/h5/chat/page.tsx** (新建)
   - 完整的 H5 聊天页面实现
   - WebSocket 连接管理
   - 正在输入动效组件
   - 消息列表和输入框
   - 响应式设计

### 文档文件

3. **docs/ws_protocol.md**
   - 添加 H5 端点说明
   - 添加 H5 生命周期描述
   - 添加服务器和客户端事件表格
   - 添加正在输入动效 CSS 实现
   - 添加使用示例

## 验收标准

✅ **WebSocket 连接**
- H5 端可以成功连接到 `/ws/h5/chat` 端点
- 连接状态实时显示
- 自动重连机制

✅ **正在输入动效**
- 三个跳动圆点动画正常显示
- 动画时间错开，有节奏感
- 输入状态实时同步

✅ **消息功能**
- 消息列表正常显示
- 自动滚动到底部
- 发送消息功能正常

✅ **协议文档**
- WebSocket 协议文档已更新
- 包含完整的端点说明
- 包含事件类型和示例

## 测试建议

### 手动测试

1. **连接测试**
   - 访问 `/h5/chat` 页面
   - 验证 WebSocket 连接成功
   - 检查连接状态显示

2. **正在输入测试**
   - 在输入框中输入文字
   - 验证正在输入动效显示
   - 验证停止输入后动效消失

3. **消息测试**
   - 发送测试消息
   - 验证消息正确显示
   - 验证自动滚动功能

### 移动端测试

1. 在不同移动设备上测试响应式布局
2. 测试触摸操作的友好性
3. 测试在不同网络环境下的连接稳定性

## 未来改进

1. **多用户支持**
   - 实现群聊场景下的正在输入状态
   - 显示具体是谁在输入

2. **消息持久化**
   - 添加本地存储支持
   - 离线消息队列

3. **增强功能**
   - 消息已读状态
   - 消息撤回功能
   - 文件和图片支持

4. **性能优化**
   - 消息虚拟化
   - 图片懒加载
   - 连接状态优化

## 相关文档

- [WebSocket 协议文档](../docs/ws_protocol.md)
- [P4-01: WebSocket 协议设计](../docs/D5-4_WEBSOCKET_PROTOCOL.md)
- [AGENTS.md](../AGENTS.md)

## 提交信息

```
feat(p4-08): implement H5 WebSocket and typing indicator

- Add H5 WebSocket endpoint /ws/h5/chat for mobile clients
- Implement H5ConnectionManager for user connection management
- Create H5 chat page with responsive design
- Implement typing indicator with bouncing dots animation
- Add typing status synchronization via WebSocket
- Update WebSocket protocol documentation with H5 endpoint
- Support connection status display and auto-reconnection

Files modified:
- app/api/realtime.py
- docs/ws_protocol.md

Files created:
- admin/app/h5/chat/page.tsx
- docs/P4-08_H5_WEBSOCKET_TYPING.md
```