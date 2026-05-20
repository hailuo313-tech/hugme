# P4-10: 移动端推送服务（FCM/APNs）

## 概述

本文档描述了 ERIS 项目中移动端推送服务的实现，支持 Firebase Cloud Messaging（FCM）用于 Android 和 Apple Push Notification service（APNs）用于 iOS。

## 任务信息

- **任务编号**: P4-10
- **任务名称**: App FCM/APNs 推送集成
- **阶段**: Phase 04
- **周次**: Week 9
- **负责人**: devin
- **权重**: 2
- **验收标准**: 真机收到推送

## 实现概览

### 1. 核心服务

#### `app/services/mobile_push_service.py`

移动端推送服务的主要实现，包含：

- **MobilePushService 类**: 管理移动端推送的核心服务
  - `send_fcm_notification()`: 发送 FCM 推送（Android）
  - `send_apns_notification()`: 发送 APNs 推送（iOS）
  - `send_notification()`: 根据平台自动选择推送服务
  - `_init_firebase()`: 初始化 Firebase Admin SDK

- **PushResult 数据类**: 推送结果封装
  - `success`: 是否成功
  - `device_token`: 设备令牌
  - `provider`: 推送提供商（"fcm" 或 "apns"）
  - `error_message`: 错误信息（失败时）
  - `message_id`: 消息ID（成功时）

- **get_mobile_push_service()**: 获取全局单例

### 2. 配置

#### `app/core/config.py`

新增配置项：

```python
# P4-10：移动端推送服务配置（FCM/APNs）
FCM_ENABLED: bool = False  # 是否启用 FCM（Android）
FCM_CREDENTIALS_PATH: Optional[str] = None  # Firebase 服务账号密钥文件路径
APNS_ENABLED: bool = False  # 是否启用 APNs（iOS）
APNS_TEAM_ID: Optional[str] = None  # Apple Team ID
APNS_KEY_ID: Optional[str] = None  # APNs Key ID
APNS_KEY_PATH: Optional[str] = None  # APNs 私钥文件路径（.p8）
APNS_BUNDLE_ID: str = 'com.hugme.app'  # App Bundle ID
APNS_PRODUCTION: bool = False  # 是否使用生产环境 APNs（False = 开发环境）
```

#### `.env.example`

新增环境变量：

```bash
# P4-10：移动端推送服务配置（FCM/APNs）
FCM_ENABLED=false
FCM_CREDENTIALS_PATH=/path/to/firebase-service-account.json
APNS_ENABLED=false
APNS_TEAM_ID=YOUR_TEAM_ID
APNS_KEY_ID=YOUR_KEY_ID
APNS_KEY_PATH=/path/to/APNs_Auth_KEY_YOUR_KEY_ID.p8
APNS_BUNDLE_ID=com.hugme.app
APNS_PRODUCTION=false
```

### 3. 依赖

#### `app/requirements.txt`

新增依赖：

```
firebase-admin==6.5.0
```

注意：`httpx` 已存在于项目中，无需额外添加。

### 4. API 集成

#### `app/api/notifications.py`

更新通知 API 以支持移动端推送：

- **ALLOWED_CHANNELS**: 新增 `"android"` 和 `"ios"`
- **NotificationSendNow 模型**: 新增移动端推送专用字段
  - `device_token`: 设备令牌（移动端推送必需）
  - `platform`: 平台类型（"android" 或 "ios"，移动端推送必需）
- **send-now 端点**: 根据 channel 路由到不同的推送服务
  - `telegram`: 原有的 Telegram 推送
  - `android`: FCM 推送
  - `ios`: APNs 推送

## 使用方法

### 1. 配置环境变量

在 `.env` 文件中配置相应的环境变量：

#### FCM 配置（Android）

```bash
FCM_ENABLED=true
FCM_CREDENTIALS_PATH=/path/to/firebase-service-account.json
```

#### APNs 配置（iOS）

```bash
APNS_ENABLED=true
APNS_TEAM_ID=YOUR_TEAM_ID
APNS_KEY_ID=YOUR_KEY_ID
APNS_KEY_PATH=/path/to/APNs_Auth_KEY_YOUR_KEY_ID.p8
APNS_BUNDLE_ID=com.hugme.app
APNS_PRODUCTION=false  # 开发环境设为 false，生产环境设为 true
```

### 2. 发送推送通知

#### 通过 API 发送

**Android 推送**：

```bash
POST /api/v1/notifications/send-now
{
  "user_id": "user-uuid",
  "channel": "android",
  "notification_type": "user_upgrade",
  "device_token": "firebase_device_token",
  "platform": "android",
  "payload": {
    "title": "升级通知",
    "body": "恭喜您升级到高级会员！",
    "custom_data": "value"
  }
}
```

**iOS 推送**：

```bash
POST /api/v1/notifications/send-now
{
  "user_id": "user-uuid",
  "channel": "ios",
  "notification_type": "user_upgrade",
  "device_token": "apns_device_token",
  "platform": "ios",
  "payload": {
    "title": "升级通知",
    "body": "恭喜您升级到高级会员！",
    "custom_data": "value"
  }
}
```

#### 通过代码调用

```python
from services.mobile_push_service import get_mobile_push_service

push_service = get_mobile_push_service()

# Android 推送
result = await push_service.send_fcm_notification(
    device_token="firebase_device_token",
    title="升级通知",
    body="恭喜您升级到高级会员！",
    data={"custom_key": "custom_value"}
)

# iOS 推送
result = await push_service.send_apns_notification(
    device_token="apns_device_token",
    title="升级通知",
    body="恭喜您升级到高级会员！",
    data={"custom_key": "custom_value"}
)

# 自动选择平台
result = await push_service.send_notification(
    device_token="device_token",
    platform="android",  # 或 "ios"
    title="升级通知",
    body="恭喜您升级到高级会员！",
    data={"custom_key": "custom_value"}
)
```

### 3. 测试

运行测试：

```bash
pytest tests/test_mobile_push_service.py -v
```

## 架构设计

### 推送流程

```
Client Request
    ↓
Notification API (/api/v1/notifications/send-now)
    ↓
Channel Routing (telegram/android/ios)
    ↓
MobilePushService
    ↓
├─ FCM (Android) → Firebase Admin SDK → FCM Server → Device
└─ APNs (iOS) → HTTP Client → APNs Server → Device
```

### 错误处理

- 推送服务在禁用或依赖缺失时会优雅降级
- 所有推送失败都会记录详细的错误日志
- 推送结果通过 `PushResult` 对象返回，包含成功状态和错误信息

### 日志记录

使用结构化日志记录推送操作：

- 成功：`notification.send_now.sent`
- 失败：包含详细错误信息和错误类型
- 包含 trace_id 用于追踪

## 安全考虑

1. **密钥管理**:
   - Firebase 服务账号密钥文件不应提交到版本控制
   - APNs 私钥文件（.p8）不应提交到版本控制
   - 使用环境变量或密钥管理系统存储敏感信息

2. **设备令牌**:
   - 设备令牌应安全存储在客户端
   - 传输过程中使用 HTTPS

3. **权限控制**:
   - 推送 API 需要适当的身份验证
   - 遵循现有的用户权限和风控规则

## 性能优化

1. **延迟初始化**: Firebase Admin SDK 在首次使用时才初始化
2. **单例模式**: 推送服务使用全局单例，避免重复初始化
3. **异步操作**: 所有推送操作都是异步的，不会阻塞主线程

## 测试覆盖

测试文件：`tests/test_mobile_push_service.py`

覆盖的场景：
- 服务初始化
- 单例模式
- FCM 禁用时的行为
- APNs 禁用时的行为
- 不支持的平台
- Firebase 初始化成功
- FCM 发送成功
- APNs 发送成功
- APNs 发送失败
- PushResult 数据类

## 故障排查

### FCM 推送失败

1. 检查 `FCM_ENABLED` 是否为 `true`
2. 检查 `FCM_CREDENTIALS_PATH` 是否正确
3. 检查 Firebase 服务账号密钥文件是否存在
4. 检查设备令牌是否有效
5. 查看日志中的详细错误信息

### APNs 推送失败

1. 检查 `APNS_ENABLED` 是否为 `true`
2. 检查 `APNS_TEAM_ID` 和 `APNS_KEY_ID` 是否正确
3. 检查 `APNS_KEY_PATH` 是否正确
4. 检查 `APNS_BUNDLE_ID` 是否与 App 一致
5. 检查 `APNS_PRODUCTION` 设置是否正确
6. 检查设备令牌是否有效
7. 查看日志中的详细错误信息

### 依赖缺失

如果看到 "firebase_admin not installed" 或 "httpx not installed" 警告：

```bash
pip install firebase-admin httpx
```

或更新 requirements：

```bash
pip install -r app/requirements.txt
```

## 未来扩展

1. **推送模板**: 支持预定义的推送模板
2. **批量推送**: 支持批量发送推送通知
3. **推送统计**: 添加推送送达率和打开率统计
4. **推送调度**: 支持定时推送
5. **多语言**: 支持多语言推送内容

## 相关文档

- [Firebase Cloud Messaging 文档](https://firebase.google.com/docs/cloud-messaging)
- [Apple Push Notification Service 文档](https://developer.apple.com/documentation/usernotifications)
- [项目 AGENTS.md](../AGENTS.md)
- [通知 API 文档](../app/api/notifications.py)

## 变更历史

- 2026-05-19: 初始实现（P4-10）