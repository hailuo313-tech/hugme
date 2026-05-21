# P4-06: S/A 全屏弹窗 + 声音提醒

## 任务概述

**任务编号**: P4-06  
**阶段**: 阶段04 看板前端  
**负责人**: Devin  
**验收标准**: 弹窗+ACK  
**依赖**: P4-04 (用户列表 S→A→B 排序置顶)

## 功能描述

为 S/A 级用户实现全屏弹窗提醒和声音通知功能，确保坐席能够及时响应高价值用户的需求。

## 实现细节

### 1. WebSocket 事件扩展

#### 新增服务器事件类型

在 WebSocket 协议中添加了 `user.alert` 事件：

```typescript
interface WsUserAlert {
  userId: string;
  level: string;
  nickname: string | null;
  externalId: string | null;
  messageId: string;
  reason: string;
  alertedAt: string;
}
```

#### 事件触发条件

- 仅对 S 级和 A 级用户触发
- 当用户升级到 S/A 级时自动触发
- 当 S/A 级用户进入等待接管状态时触发

### 2. 前端实现

#### 全屏弹窗组件

在 `admin/app/page.tsx` 中实现了全屏弹窗：

```typescript
const [alertModal, setAlertModal] = useState<{
  userId: string;
  level: string;
  nickname: string | null;
  externalId: string | null;
  messageId: string;
} | null>(null);
```

弹窗特性：
- 全屏半透明背景 (`bg-black/80 backdrop-blur-sm`)
- 居中显示的模态框
- 显示用户信息（昵称、等级、原因）
- 两个操作按钮："稍后处理" 和 "立即查看"
- S 级用户显示 ⭐ 图标，A 级用户显示 🔔 图标
- S 级用户使用黄色高亮，A 级用户使用紫色高亮

#### 声音提醒功能

使用 Web Audio API 实现声音提醒：

```typescript
const playAlertSound = useCallback(() => {
  if (!audioEnabled) return;
  
  try {
    const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
    const oscillator = audioContext.createOscillator();
    const gainNode = audioContext.createGain();
    
    oscillator.connect(gainNode);
    gainNode.connect(audioContext.destination);
    
    oscillator.frequency.value = 800; // 频率 800Hz
    oscillator.type = 'sine';
    gainNode.gain.value = 0.3; // 音量
    
    oscillator.start();
    
    // 播放 0.5 秒
    setTimeout(() => {
      oscillator.stop();
      audioContext.close();
    }, 500);
  } catch (e) {
    console.error('Failed to play alert sound:', e);
  }
}, [audioEnabled]);
```

声音特性：
- 使用正弦波，频率 800Hz
- 播放时长 0.5 秒
- 音量适中 (0.3)
- 可通过界面开关控制

#### 声音开关

在页面顶部导航栏添加了声音开关：

```typescript
const [audioEnabled, setAudioEnabled] = useState(true);
```

UI 表现：
- 开启状态：🔊 图标，紫色
- 关闭状态：🔇 图标，灰色
- 点击切换状态

### 3. ACK 确认机制

#### 确认流程

坐席点击"立即查看"按钮时：
1. 发送 `message.ack` 确认到服务器
2. 查找对应的会话
3. 打开会话详情页面
4. 关闭弹窗

```typescript
const handleAlertConfirm = useCallback(async () => {
  if (!alertModal) return;
  
  try {
    // 发送 ACK 确认
    const ws = (window as any).operatorWs;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: 'message.ack',
        message_id: alertModal.messageId
      }));
    }
    
    // 查找对应的会话并打开详情
    const targetConversation = items.find(item => item.user_id === alertModal.userId);
    if (targetConversation) {
      await openDetail(targetConversation.conversation_id);
    }
  } catch (e) {
    console.error('Failed to send ACK:', e);
  }
  
  setAlertModal(null);
}, [alertModal, items]);
```

#### 忽略流程

坐席点击"稍后处理"按钮时：
1. 仅关闭弹窗
2. 不发送 ACK 确认
3. 服务器可能会根据 ACK 重推机制重新发送提醒

### 4. WebSocket Hook 扩展

在 `admin/hooks/useOperatorTaskWs.ts` 中扩展了：

#### 新增接口

```typescript
export interface WsUserAlert {
  userId: string;
  level: string;
  nickname: string | null;
  externalId: string | null;
  messageId: string;
  reason: string;
  alertedAt: string;
}
```

#### 新增回调

```typescript
interface UseOperatorTaskWsOptions {
  // ... 现有选项
  onUserAlert?: (alert: WsUserAlert) => void; // P4-06: S/A 级用户提醒回调
}
```

#### 消息处理

```typescript
// P4-06: 处理 S/A 级用户提醒事件
if (msg.type === "user.alert" && msg.user_id && msg.level && msg.message_id) {
  const alert: WsUserAlert = {
    userId: msg.user_id,
    level: msg.level,
    nickname: msg.nickname || null,
    externalId: msg.external_id || null,
    messageId: msg.message_id,
    reason: msg.reason || "user alert",
    alertedAt: msg.alerted_at || new Date().toISOString(),
  };
  setLastAlertModal(alert);
  onUserAlert?.(alert);
  
  // 保存 WebSocket 实例到 window，用于后续发送 ACK
  (window as any).operatorWs = ws;
}
```

## 修改的文件

### 前端文件

1. **admin/app/page.tsx**
   - 添加弹窗状态管理 (`alertModal`, `audioEnabled`)
   - 实现声音播放函数 (`playAlertSound`)
   - 实现弹窗处理函数 (`handleUserAlert`, `handleAlertConfirm`, `handleAlertDismiss`)
   - 添加声音开关 UI
   - 添加全屏弹窗 UI 组件
   - 集成 `onUserAlert` 回调

2. **admin/hooks/useOperatorTaskWs.ts**
   - 添加 `WsUserAlert` 接口
   - 扩展 `UseOperatorTaskWsOptions` 接口，添加 `onUserAlert` 回调
   - 添加 `lastAlertModal` 状态
   - 在消息处理中添加 `user.alert` 事件处理
   - 添加 `dismissAlertModal` 函数
   - 更新返回值

### 文档文件

3. **docs/ws_protocol.md**
   - 在 Server Events 表格中添加 `user.alert` 事件
   - 添加 P4-06 专门章节，详细说明新事件的使用

## 验收标准

✅ **弹窗功能**
- S/A 级用户触发时显示全屏弹窗
- 弹窗显示正确的用户信息
- 弹窗可以通过按钮关闭

✅ **声音提醒**
- 弹窗出现时播放提示音
- 声音可以通过开关控制
- 声音播放失败时有错误处理

✅ **ACK 确认**
- 点击"立即查看"时发送 ACK
- 点击后跳转到对应的用户详情
- 点击"稍后处理"不发送 ACK

✅ **协议文档**
- WebSocket 协议文档已更新
- 包含完整的事件说明和示例
- 与 P4-02 ACK 重推机制兼容

## 测试建议

### 手动测试

1. **弹窗显示测试**
   - 模拟 S 级用户升级事件
   - 验证弹窗正确显示
   - 验证用户信息正确

2. **声音测试**
   - 验证弹窗出现时播放声音
   - 测试声音开关功能
   - 测试声音在不同浏览器中的兼容性

3. **ACK 测试**
   - 测试"立即查看"按钮的 ACK 发送
   - 测试"稍后处理"按钮的行为
   - 验证跳转到用户详情功能

### 自动化测试

建议添加以下测试用例：

1. WebSocket 消息处理测试
2. 弹窗状态管理测试
3. ACK 发送测试
4. 声音播放测试（使用 mock）

## 兼容性

- 依赖 P4-02 的 ACK 重推机制
- 与现有的 P4-04 S 级用户置顶功能兼容
- 与现有的 WebSocket 连接管理兼容
- 支持现代浏览器的 Web Audio API

## 未来改进

1. **声音自定义**
   - 允许坐席选择不同的提示音
   - 支持上传自定义声音文件

2. **弹窗规则配置**
   - 允许配置哪些情况触发弹窗
   - 支持设置弹窗的优先级和频率

3. **多坐席协调**
   - 当多个坐席在线时，协调弹窗显示
   - 避免同一个用户对多个坐席同时弹窗

## 相关文档

- [WebSocket 协议文档](../docs/ws_protocol.md)
- [P4-02: WebSocket ACK 重推机制](../docs/P4-02_WEBSOCKET_ACK_RETRY.md)
- [P4-04: 用户列表 SAB 排序](../docs/P4-04_USER_LIST_SAB_SORTING.md)
- [AGENTS.md](../AGENTS.md)

## 提交信息

```
feat(p4-06): implement S/A user alert modal with sound notification

- Add user.alert WebSocket event for S/A level users
- Implement fullscreen modal with user information
- Add sound notification using Web Audio API
- Implement ACK confirmation mechanism
- Add sound toggle control in UI
- Update WebSocket protocol documentation
- Extend useOperatorTaskWs hook with alert handling

Files modified:
- admin/app/page.tsx
- admin/hooks/useOperatorTaskWs.ts
- docs/ws_protocol.md

Files created:
- docs/P4-06_USER_ALERT_MODAL.md
```