# P4-04: 用户列表 SAB 排序置顶

> **状态**: ✅ 已完成  
> **验收标准**: 新 S 级 3s 置顶  
> **实现日期**: 2026-05-21

## 概述

本任务实现了用户列表的 SAB（S、A、B 级）排序置顶功能，以及新 S 级用户 3 秒自动置顶机制。

## 实现内容

### 1. SAB 级别排序置顶

#### 后端排序逻辑
- 更新 `app/services/dashboard_integration.py` 中的 SQL 排序
- 优先按 S→A→B→C→D 级别排序
- 然后按状态排序（WAITING_OPERATOR→HUMAN_LOCKED→AI_ACTIVE→CLOSED）
- 最后按 handoff_count 和最后消息时间排序

#### 前端排序逻辑
- 在 `admin/app/page.tsx` 中添加前端排序函数
- 与后端排序逻辑保持一致
- 支持客户端实时排序

### 2. S 级用户 3 秒置顶机制

#### 置顶状态管理
- 添加 `priorityUserIds` 状态跟踪置顶用户
- 添加 `handlePriorityUser` 函数处理置顶逻辑
- 3 秒后自动移除置顶状态

#### WebSocket 事件监听
- 扩展 `useOperatorTaskWs` hook，添加 `onUserUpgraded` 回调
- 监听 `user.upgraded` WebSocket 事件
- 当检测到 S 级用户升级时，触发置顶机制

#### UI 通知
- 添加 S 级用户升级通知横幅
- 显示升级信息（原等级 → S 级）
- 提供关闭按钮
- 自动 3 秒后消失

## 文件变更

### 修改文件
- `app/services/dashboard_integration.py`：
  - 更新 `sql_order_clause_for_dashboard()` 函数
  - 实现按 S→A→B→C→D 级别优先排序

- `admin/app/page.tsx`：
  - 添加 SAB 级别排序权重常量
  - 实现 `sortConversationsByLevelAndState()` 函数
  - 添加 S 级用户置顶状态管理
  - 集成 WebSocket 用户升级事件处理
  - 添加 S 级用户升级通知横幅

- `admin/hooks/useOperatorTaskWs.ts`：
  - 添加 `WsUserUpgrade` 接口
  - 添加 `onUserUpgraded` 回调参数
  - 实现 `user.upgraded` 事件处理
  - 添加 `lastUpgrade` 状态和 `dismissUpgrade` 函数

### 新增文件
- `docs/P4-04_USER_LIST_SAB_SORTING.md`：任务文档

## 技术实现

### 排序优先级

#### 等级优先级
```
S (VIP >= 3) -> 0
A (VIP >= 2) -> 1
B (VIP >= 1) -> 2
C (VIP < 1) -> 3
D (VIP < 1) -> 4
```

#### 状态优先级
```
WAITING_OPERATOR -> 0
HUMAN_LOCKED -> 1
AI_ACTIVE -> 2
CLOSED -> 3
```

### 置顶机制

#### 触发条件
- 通过 WebSocket 接收 `user.upgraded` 事件
- 新等级为 "S"

#### 置顶流程
1. 接收 `user.upgraded` 事件
2. 检查新等级是否为 "S"
3. 将用户 ID 添加到 `priorityUserIds` 集合
4. 重新加载列表应用新排序
5. 3 秒后从集合中移除用户 ID
6. 重新加载列表恢复正常排序

#### 排序逻辑
```javascript
// 1. 优先处理置顶的 S 级用户
if (priorityUserIds.has(userId)) {
  return -1; // 置顶
}

// 2. 按等级排序 (S→A→B→C→D)
// 3. 按状态排序
// 4. 按 handoff_count 降序
// 5. 按最后消息时间降序
```

## 使用说明

### 正常排序
用户列表默认按 S→A→B→C→D 级别排序，同级内按状态和时间排序。

### S 级用户置顶
当有用户升级为 S 级时：
1. 页面顶部显示通知横幅
2. 该用户在列表中自动置顶
3. 3 秒后恢复正常排序位置
4. 通知横幅消失

### WebSocket 事件格式
```json
{
  "type": "user.upgraded",
  "trace_id": "ws-op-1",
  "user_id": "uuid",
  "previous_level": "B",
  "new_level": "S",
  "reason": "payment_completed",
  "upgraded_at": "2026-05-19T19:00:00"
}
```

## 验收标准

- ✅ 用户列表按 S→A→B→C→D 级别排序
- ✅ 同级内按状态和时间排序
- ✅ 新 S 级用户 3 秒内自动置顶
- ✅ 显示 S 级用户升级通知
- ✅ 3 秒后恢复正常排序
- ✅ WebSocket 事件正确处理
- ✅ 前后端排序逻辑一致

## 部署注意事项

1. **环境变量**：无需新增环境变量
2. **数据库变更**：无需数据库变更（使用现有字段）
3. **向后兼容**：完全兼容现有功能
4. **性能影响**：
   - 前端排序在客户端进行，影响较小
   - 后端 SQL 排序已优化，性能良好
5. **WebSocket 配置**：需要确保 user.upgraded 事件正常广播

## 后续优化建议

1. **配置化**：将置顶时间（3秒）移至配置文件
2. **多级置顶**：支持 A 级、B 级用户的置顶配置
3. **批量置顶**：支持多个用户同时置顶
4. **持久化**：考虑将置顶状态持久化到 localStorage
5. **动画效果**：添加置顶动画效果，提升用户体验
6. **声音提醒**：S 级用户升级时播放提示音

## 相关文档

- [P4-02 WebSocket ACK 重推机制](P4-02_WEBSOCKET_ACK_RETRY.md)
- [WebSocket 协议规范](ws_protocol.md)
- [Dashboard Integration Contract](../app/services/dashboard_integration.py)

## 测试建议

1. **功能测试**：
   - 测试不同等级用户的排序顺序
   - 测试同级内状态的排序
   - 测试 S 级用户升级置顶
   - 测试 3 秒后恢复排序
   - 测试通知横幅显示和关闭

2. **性能测试**：
   - 大量用户时的排序性能
   - 频繁升级时的性能影响
   - WebSocket 消息处理性能

3. **兼容性测试**：
   - 不同浏览器测试
   - 移动设备测试
   - 不同屏幕尺寸测试