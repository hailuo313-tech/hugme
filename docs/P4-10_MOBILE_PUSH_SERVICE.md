# P4-10: 移动端推送服务配置指南

## 任务概述

**任务编号**: P4-10  
**阶段**: 阶段04 看板前端  
**负责人**: Devin  
**验收标准**: 真机收到推送；管理界面可用  
**依赖**: 无

## 功能描述

实现完整的移动端推送服务，包括 FCM (Firebase Cloud Messaging) 用于 Android 和 APNs (Apple Push Notification service) 用于 iOS，以及完整的前端管理界面。

## 环境配置

### FCM 配置 (Android)

#### 环境变量

在 `.env` 文件中添加：

```bash
FCM_ENABLED=true
FCM_CREDENTIALS_PATH=/path/to/firebase-credentials.json
```

#### 获取 Firebase 凭证

1. 访问 [Firebase Console](https://console.firebase.google.com/)
2. 创建新项目或选择现有项目
3. 进入项目设置 > Service Accounts
4. 生成新的私钥
5. 下载 JSON 凭证文件
6. 将文件保存到服务器安全位置
7. 设置 `FCM_CREDENTIALS_PATH` 指向该文件

#### 安装依赖

```bash
pip install firebase-admin
```

### APNs 配置 (iOS)

#### 环境变量

在 `.env` 文件中添加：

```bash
APNS_ENABLED=true
APNS_TEAM_ID=YOUR_TEAM_ID
APNS_KEY_ID=YOUR_KEY_ID
APNS_KEY_PATH=/path/to/apns-auth-key.p8
APNS_BUNDLE_ID=com.hugme.app
APNS_PRODUCTION=false  # 开发环境设为 false，生产环境设为 true
```

#### 获取 APNs 凭证

1. 访问 [Apple Developer Portal](https://developer.apple.com/)
2. 进入 Certificates, Identifiers & Profiles
3. 创建 APNs Auth Key
4. 下载 .p8 格式的私钥文件
5. 记录 Team ID 和 Key ID
6. 将文件保存到服务器安全位置
7. 设置相应的环境变量

#### 安装依赖

```bash
pip install httpx
```

## 数据库迁移

运行数据库迁移以创建设备令牌表：

```bash
# 使用 psql 直接运行
psql -U your_user -d your_database -f db/migrations/V2__device_tokens.sql

# 或使用 Flyway（如果配置了）
python -m alembic upgrade head
```

## API 端点

### 设备令牌管理

#### 注册设备令牌

```http
POST /api/v1/device-tokens/devices/register
Content-Type: application/json

{
  "user_id": "user-uuid",
  "device_token": "device-token-string",
  "platform": "android",
  "device_info": {
    "model": "Pixel 6",
    "os_version": "13"
  }
}
```

#### 查询设备列表

```http
GET /api/v1/device-tokens/devices?user_id=user-uuid&platform=android&limit=50
```

#### 获取用户设备

```http
GET /api/v1/device-tokens/user/{user_id}/devices
```

#### 删除设备令牌

```http
DELETE /api/v1/device-tokens/devices/{device_token}
```

### 推送测试

#### 发送测试推送

```http
POST /api/v1/device-tokens/test-push
Content-Type: application/json

{
  "device_token": "device-token-string",
  "platform": "android",
  "title": "测试推送",
  "body": "这是一条测试消息",
  "data": {
    "custom_key": "custom_value"
  }
}
```

## 前端管理界面

### 访问地址

```
http://your-domain/admin/push
```

### 功能特性

1. **设备列表管理**
   - 查看所有已注册的设备令牌
   - 按用户 ID 或平台筛选
   - 删除设备令牌
   - 实时刷新列表

2. **推送测试**
   - 选择设备进行测试推送
   - 自定义推送标题和内容
   - 实时显示推送结果
   - 支持自定义数据

3. **配置说明**
   - 详细的配置指南
   - 环境变量说明
   - 依赖安装指导

### 界面特点

- 深色主题设计
- 响应式布局
- 实时状态反馈
- 错误处理和提示
- WebSocket 连接状态显示

## 使用示例

### 移动端注册设备令牌

```typescript
// React Native 示例
import { Platform } from 'react-native';
import messaging from '@react-native-firebase/messaging';

const registerDeviceToken = async (userId: string) => {
  try {
    const token = await messaging().getToken();
    
    const response = await fetch('https://your-api.com/api/v1/device-tokens/devices/register', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        user_id: userId,
        device_token: token,
        platform: Platform.OS, // 'android' or 'ios'
        device_info: {
          model: DeviceInfo.getModel(),
          os_version: DeviceInfo.getSystemVersion(),
        },
      }),
    });
    
    const result = await response.json();
    console.log('Device registered:', result);
  } catch (error) {
    console.error('Failed to register device:', error);
  }
};
```

### 发送推送通知

```python
from services.mobile_push_service import get_mobile_push_service

push_service = get_mobile_push_service()

# 发送 FCM 推送
result = await push_service.send_notification(
    device_token="device-token-here",
    platform="android",
    title="新消息",
    body="您有一条新消息",
    data={"conversation_id": "123", "type": "new_message"}
)

if result.success:
    print(f"Push sent successfully: {result.message_id}")
else:
    print(f"Push failed: {result.error_message}")
```

## 故障排除

### FCM 常见问题

1. **凭证文件路径错误**
   - 检查 `FCM_CREDENTIALS_PATH` 是否正确
   - 确保文件存在且可读
   - 验证文件格式是否正确

2. **权限不足**
   - 检查 Firebase 项目权限
   - 确认服务账号有 Cloud Messaging 权限

3. **设备令牌无效**
   - 设备令牌可能过期
   - 应用重新安装后需要重新注册
   - 检查设备是否正确配置了 Firebase

### APNs 常见问题

1. **证书配置错误**
   - 确认 Team ID 和 Key ID 正确
   - 检查 .p8 文件是否有效
   - 验证 Bundle ID 是否匹配

2. **生产/开发环境混淆**
   - 开发环境使用 `APNS_PRODUCTION=false`
   - 生产环境使用 `APNS_PRODUCTION=true`
   - 确保使用对应的证书

3. **设备令牌格式错误**
   - iOS 设备令牌是 64 字符的十六进制字符串
   - 确保没有多余空格或换行符
   - 验证令牌是否来自正确环境

### 数据库问题

1. **表不存在**
   - 运行数据库迁移脚本
   - 检查 migration 是否成功执行
   - 验证表结构是否正确

2. **权限问题**
   - 确保数据库用户有创建表的权限
   - 检查连接配置是否正确

## 安全建议

1. **凭证文件安全**
   - 不要将凭证文件提交到版本控制
   - 使用 .gitignore 排除凭证文件
   - 设置文件权限为 600 (仅所有者可读写)

2. **API 访问控制**
   - 设备令牌注册 API 需要用户认证
   - 推送测试 API 仅限管理员访问
   - 使用 HTTPS 加密传输

3. **日志脱敏**
   - 不要在日志中记录完整的设备令牌
   - 记录令牌的前几个字符即可
   - 敏感信息使用脱敏处理

## 性能优化

1. **批量推送**
   - 使用批量 API 减少请求次数
   - 实现推送队列处理
   - 支持异步推送

2. **缓存策略**
   - 缓存用户设备列表
   - 减少数据库查询频率
   - 使用 Redis 存储临时数据

3. **错误重试**
   - 实现指数退避重试机制
   - 记录失败推送以便后续处理
   - 监控推送成功率

## 监控建议

1. **推送成功率**
   - 监控 FCM/APNs 响应状态
   - 统计成功/失败比例
   - 设置告警阈值

2. **设备令牌管理**
   - 监控设备令牌注册/删除
   - 清理过期或无效的令牌
   - 统计活跃设备数量

3. **性能指标**
   - 监控推送延迟
   - 统计 API 响应时间
   - 监控数据库查询性能

## 相关文档

- [Firebase Cloud Messaging 文档](https://firebase.google.com/docs/cloud-messaging)
- [Apple Push Notification Service 文档](https://developer.apple.com/documentation/usernotifications)
- [移动端推送服务实现](../app/services/mobile_push_service.py)
- [设备令牌管理 API](../app/api/device_tokens.py)
- [AGENTS.md](../AGENTS.md)

## 提交信息

```
feat(p4-10): implement mobile push service with management interface

- Add device token management API (register, list, delete)
- Implement push test functionality
- Create push management interface in admin panel
- Add database migration for device_tokens table
- Integrate with existing mobile push service
- Support both FCM (Android) and APNs (iOS)
- Add comprehensive configuration documentation
- Mark P4-10 as completed in business-flow.html

Files modified:
- app/main.py
- docs/product/business-flow.html

Files created:
- app/api/device_tokens.py
- db/migrations/V2__device_tokens.sql
- admin/app/push/page.tsx
- docs/P4-10_MOBILE_PUSH_SERVICE.md
```