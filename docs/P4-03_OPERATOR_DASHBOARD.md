# P4-03: 坐席看板 React + 路由鉴权

> **状态**: ✅ 已完成  
> **验收标准**: 可登录  
> **实现日期**: 2026-05-21

## 概述

本任务实现了坐席看板前端，包括：
1. **React 坐席看板页面**：实时显示待处理任务列表
2. **路由鉴权**：基于现有 AuthGate 组件的页面保护
3. **WebSocket 实时任务推送**：集成 P4-02 的 ACK 重推机制
4. **任务管理功能**：接受/拒绝任务的操作接口

## 实现内容

### 1. 坐席看板页面

#### 新增文件
- `admin/app/operator-dashboard/page.tsx`：坐席看板主页面

#### 功能特性
- **实时任务列表**：通过 WebSocket 接收实时任务更新
- **任务优先级显示**：P0-P3 优先级，不同颜色标识
- **任务详情面板**：显示任务的详细信息
- **任务操作**：接受/拒绝任务按钮
- **WebSocket 状态监控**：实时显示连接状态
- **响应式布局**：支持桌面和移动设备

#### 页面布局
- **顶部导航栏**：
  - 返回会话总览链接
  - 坐席欢迎信息
  - WebSocket 连接状态指示
  - 待处理任务计数
  - 登出按钮
- **主内容区**：
  - 左侧：任务列表（2/3 宽度）
  - 右侧：任务详情面板（1/3 宽度）

### 2. 路由鉴权

#### 实现方式
- 使用现有的 `AuthGate` 组件进行页面保护
- 未登录用户自动跳转到登录页面
- 已登录用户才能访问坐席看板

#### 鉴权流程
1. 用户访问 `/admin/operator-dashboard`
2. `AuthGate` 检查 localStorage 中的 token
3. 无 token → 跳转到 `/admin/login`
4. 有 token → 验证并显示页面内容

### 3. WebSocket 集成

#### 连接管理
- 自动连接到 `/ws/operators/tasks?operator_id={operator_id}`
- 支持自动重连（连接断开后 3 秒重试）
- 定期发送心跳（每 25 秒）

#### 消息处理
- `connection.ready`：连接就绪
- `task.snapshot`：初始任务快照
- `task.upsert`：任务更新或新增
- `task.removed`：任务移除
- `user.upgraded`：用户升级通知
- `pong`：心跳响应

#### ACK 确认机制
- 收到带 `message_id` 的消息后自动发送 ACK
- 利用 P4-02 实现的可靠消息传递机制

### 4. 后端 API

#### 新增端点
- `POST /api/v1/admin/handoff-tasks/{task_id}/accept`：接受任务
- `POST /api/v1/admin/handoff-tasks/{task_id}/reject`：拒绝任务

#### API 逻辑
- **接受任务**：
  - 验证任务 ID 格式
  - 检查任务是否存在
  - 检查任务是否已分配
  - 更新 `handoff_tasks` 表状态
  - 更新 `conversations` 表状态
  - 记录操作日志

- **拒绝任务**：
  - 验证任务 ID 格式
  - 检查任务是否存在
  - 检查任务是否分配给当前坐席
  - 更新 `handoff_tasks` 表状态
  - 更新 `conversations` 表状态
  - 记录操作日志

### 5. 导航集成

#### 主页面更新
- 在 `admin/app/page.tsx` 添加"坐席看板"按钮
- 链接到 `/admin/operator-dashboard`

#### 坐席看板页面
- 添加"返回会话总览"链接
- 链接到 `/admin`

## 文件变更

### 新增文件
- `admin/app/operator-dashboard/page.tsx`：坐席看板主页面（450+ 行）
- `docs/P4-03_OPERATOR_DASHBOARD.md`：任务文档

### 修改文件
- `admin/app/page.tsx`：添加坐席看板导航链接
- `app/api/admin.py`：添加任务接受/拒绝 API 端点（+140 行）

## 技术栈

### 前端
- **框架**：Next.js 15.5.18（App Router）
- **UI**：Tailwind CSS 3.4.1
- **状态管理**：React Hooks（useState, useEffect）
- **WebSocket**：原生 WebSocket API
- **鉴权**：现有 AuthGate 组件

### 后端
- **框架**：FastAPI
- **数据库**：PostgreSQL（AsyncSession）
- **鉴权**：JWT（HS256）

## 使用说明

### 访问坐席看板
1. 登录运营后台：`/admin/login`
2. 点击"坐席看板"按钮或直接访问 `/admin/operator-dashboard`
3. 页面会自动连接 WebSocket 并显示任务列表

### 任务操作
1. **查看任务**：点击任务列表中的任务查看详情
2. **接受任务**：点击"接受"按钮，任务将分配给当前坐席
3. **拒绝任务**：点击"拒绝"按钮，任务将重新变为待分配状态
4. **开始处理**：对于已接受的任务，点击"开始处理"跳转到对话详情页

### WebSocket 状态
- **绿色**：已连接，正常运行
- **黄色（闪烁）**：连接中
- **红色**：已断开，正在重连

## 验收标准

- ✅ 可以正常登录运营后台
- ✅ 登录后可以访问坐席看板页面
- ✅ 路由鉴权正常工作（未登录自动跳转）
- ✅ WebSocket 连接正常
- ✅ 任务列表实时更新
- ✅ 任务接受/拒绝功能正常
- ✅ 页面布局响应式适配
- ✅ 导航链接正常工作

## 部署注意事项

1. **环境变量**：无需新增环境变量
2. **数据库变更**：无需数据库变更（使用现有表）
3. **向后兼容**：完全兼容现有功能
4. **WebSocket 配置**：确保后端 WebSocket 端点正常工作
5. **CORS 配置**：如需跨域访问，需配置 CORS

## 后续优化建议

1. **任务过滤**：添加按优先级、状态、时间等过滤功能
2. **批量操作**：支持批量接受/拒绝任务
3. **任务统计**：添加任务处理统计和报表
4. **声音提醒**：高优先级任务到达时播放提示音
5. **移动端优化**：进一步优化移动端体验
6. **离线支持**：考虑添加离线缓存和同步功能
7. **性能优化**：大量任务时的虚拟滚动优化

## 相关文档

- [P4-02 WebSocket ACK 重推机制](P4-02_WEBSOCKET_ACK_RETRY.md)
- [WebSocket 协议规范](ws_protocol.md)
- [D5-4 WebSocket Task Push Protocol](../D5-4_WEBSOCKET_PROTOCOL.md)
- [运营后台登录页面](../admin/app/login/page.tsx)

## 测试建议

1. **功能测试**：
   - 测试登录后访问坐席看板
   - 测试未登录访问时的鉴权跳转
   - 测试任务接受/拒绝功能
   - 测试 WebSocket 连接和重连

2. **兼容性测试**：
   - 不同浏览器测试
   - 移动设备测试
   - 不同屏幕尺寸测试

3. **性能测试**：
   - 大量任务时的页面性能
   - WebSocket 消息处理性能
   - 内存使用情况