# P1-20 账号在线率/发送成功率监控 + 封号预警埋点 - 验证文档

## 任务描述

**P1-20**: 账号在线率/发送成功率监控 + 封号预警埋点
**验收标准**: 指标可 scrape + 告警规则

## 实现内容

### 1. 账号监控服务

- **文件**: `app/services/account_monitor.py` (新增)
- **功能**:
  - 定期收集账号统计信息（在线状态、发送成功率、错误率）
  - Prometheus metrics 暴露（ Gauge、Counter、Histogram）
  - 历史数据保留和清理
  - 与 telegram_account_manager 集成

### 2. 监控 API 端点

- **文件**: `app/api/monitoring.py` (新增)
- **端点**:
  - `GET /api/v1/monitoring/accounts/{account_id}` - 获取单个账号统计
  - `GET /api/v1/monitoring/accounts` - 获取所有账号统计
  - `GET /api/v1/monitoring/summary` - 获取汇总统计
  - `POST /api/v1/monitoring/send-attempt` - 记录发送尝试
  - `POST /api/v1/monitoring/start` - 启动监控服务
  - `POST /api/v1/monitoring/stop` - 停止监控服务
  - `GET /api/v1/monitoring/health` - 获取监控服务健康状态

### 3. 告警调度器

- **文件**: `app/services/alert_scheduler.py` (新增)
- **功能**:
  - 定期检查告警条件
  - 支持多种告警规则（封号、离线、高错误率、低成功率等）
  - 告警冷却机制
  - 告警历史记录
  - 告警自动解析

### 4. 告警规则配置

- **文件**: `config/alert_rules.json` (新增)
- **预置规则**:
  - `account_banned` - 账号封禁告警（critical）
  - `account_offline` - 账号离线告警（warning）
  - `high_error_rate` - 高错误率告警（error）
  - `low_success_rate` - 低成功率告警（warning）
  - `long_offline_duration` - 长时间离线告警（error）
  - `critical_error_rate` - 严重错误率告警（critical）

### 5. 配置

- **文件**: `app/core/config.py` (已更新)
- **新增配置项**:
  - `ACCOUNT_MONITOR_ENABLED`: 是否启用账号监控 (默认: False)
  - `ACCOUNT_MONITOR_METRICS_PORT`: Prometheus metrics 端口 (默认: 9091)
  - `ACCOUNT_MONITOR_COLLECTION_INTERVAL`: 数据收集间隔 (默认: 60秒)
  - `ACCOUNT_MONITOR_HISTORY_RETENTION_HOURS`: 历史数据保留时长 (默认: 24小时)
  - `ALERT_SCHEDULER_ENABLED`: 是否启用告警调度器 (默认: False)
  - `ALERT_SCHEDULER_CHECK_INTERVAL`: 告警检查间隔 (默认: 60秒)
  - `ALERT_RULES_PATH`: 告警规则配置文件路径 (默认: config/alert_rules.json)

### 6. 集成

- **文件**: `app/main.py` (已更新)
- **集成内容**:
  - 应用启动时自动启动账号监控和告警调度器 (如果启用)
  - 应用关闭时自动停止账号监控和告警调度器
  - 注册 monitoring API router

## Prometheus Metrics

### Gauge 指标

- `eris_telegram_account_online` - 账号在线状态 (1=在线, 0=离线)
  - 标签: account_id, phone

- `eris_telegram_account_connection_duration_seconds` - 账号连接时长（秒）
  - 标签: account_id, phone

- `eris_telegram_message_send_success_rate` - 消息发送成功率 (0-1)
  - 标签: account_id, phone

- `eris_telegram_account_banned` - 账号封禁状态 (1=封禁, 0=活跃)
  - 标签: account_id, phone

- `eris_telegram_account_error_rate` - 账号错误率（最近1小时）
  - 标签: account_id, phone

### Counter 指标

- `eris_telegram_message_send_attempts_total` - 消息发送尝试总数
  - 标签: account_id, phone, status (success/failure)

### Histogram 指标

- `eris_account_monitor_collection_duration_seconds` - 监控数据收集耗时

## 验收标准验证

### ✅ 验收标准: 指标可 scrape + 告警规则

**验证步骤**:

1. **准备环境**:
   ```bash
   # 设置环境变量
   export ACCOUNT_MONITOR_ENABLED=true
   export ALERT_SCHEDULER_ENABLED=true
   ```

2. **启动应用**:
   ```bash
   cd /e/eris/app
   python -m uvicorn main:app --reload
   ```

3. **验证 Prometheus metrics**:
   ```bash
   # 检查 metrics 端口
   curl http://localhost:9091/metrics

   # 应该看到以下指标:
   # eris_telegram_account_online{account_id="...",phone="..."} 1.0
   # eris_telegram_account_connection_duration_seconds{account_id="...",phone="..."} 123.45
   # eris_telegram_message_send_success_rate{account_id="...",phone="..."} 1.0
   # eris_telegram_account_banned{account_id="...",phone="..."} 0.0
   # eris_telegram_account_error_rate{account_id="...",phone="..."} 0.0
   ```

4. **验证 API 端点**:
   ```bash
   # 获取所有账号统计
   curl http://localhost:8000/api/v1/monitoring/accounts

   # 获取汇总统计
   curl http://localhost:8000/api/v1/monitoring/summary

   # 获取监控服务健康状态
   curl http://localhost:8000/api/v1/monitoring/health
   ```

5. **验证告警规则**:
   ```bash
   # 检查告警规则配置
   cat config/alert_rules.json

   # 应该看到预置的6条告警规则
   ```

6. **验证告警触发**:
   ```bash
   # 模拟账号离线（断开连接）
   # 等待告警检查周期（默认60秒）

   # 检查日志，应该看到告警触发日志:
   # Alert triggered: account_offline for account ... - Account is offline
   ```

7. **验证告警解析**:
   ```bash
   # 恢复账号连接
   # 等待告警检查周期

   # 检查日志，应该看到告警解析日志:
   # Alert resolved: account_offline for account ...
   ```

## 功能特性

### 1. 账号监控

- ✅ 定期收集账号统计信息（默认60秒）
- ✅ 在线状态跟踪
- ✅ 连接时长计算
- ✅ 发送成功率计算
- ✅ 错误率计算
- ✅ 历史数据保留（默认24小时）
- ✅ Prometheus metrics 暴露

### 2. 告警系统

- ✅ 可配置的告警规则
- ✅ 多种告警级别（info, warning, error, critical）
- ✅ 告警冷却机制
- ✅ 告警历史记录
- ✅ 告警自动解析
- ✅ 支持动态规则重载

### 3. API 管理

- ✅ 获取单个/所有账号统计
- ✅ 获取汇总统计
- ✅ 记录发送尝试
- ✅ 启动/停止监控服务
- ✅ 健康检查端点

## 测试场景

### 场景 1: 正常监控

1. 启用监控服务
2. 添加并连接 Telegram 账号
3. **预期**: Prometheus metrics 正常更新，API 返回正确统计

### 场景 2: 账号离线告警

1. 账号正常连接
2. 断开账号连接
3. **预期**: 60秒内触发 account_offline 告警

### 场景 3: 账号封禁告警

1. 模拟账号被封禁（status=banned）
2. **预期**: 立即触发 account_banned 告警（critical）

### 场景 4: 高错误率告警

1. 模拟账号错误率 > 50%
2. **预期**: 触发 high_error_rate 告警

### 场景 5: 告警冷却

1. 触发告警后
2. 条件仍然满足
3. **预期**: 在冷却期内不会重复触发告警

### 场景 6: 告警解析

1. 告警触发后
2. 条件不再满足
3. **预期**: 告警自动标记为已解析

## Prometheus 配置

在 Prometheus 配置文件中添加 scrape 配置:

```yaml
scrape_configs:
  - job_name: 'eris-accounts'
    static_configs:
      - targets: ['localhost:9091']
    scrape_interval: 60s
```

## Grafana 仪表板示例

### 账号在线率面板

```
Query: sum(eris_telegram_account_online) / count(eris_telegram_account_online)
```

### 账号发送成功率面板

```
Query: avg(eris_telegram_message_send_success_rate)
```

### 账号错误率面板

```
Query: avg(eris_telegram_account_error_rate)
```

## 告警规则示例

### Prometheus Alertmanager 配置

```yaml
groups:
  - name: eris_accounts
    rules:
      - alert: AccountOffline
        expr: eris_telegram_account_online == 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Account {{ $labels.phone }} is offline"

      - alert: AccountBanned
        expr: eris_telegram_account_banned == 1
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Account {{ $labels.phone }} is banned"
```

## 依赖项

- `prometheus_client` - Prometheus metrics 库
- `telethon` - Telegram 客户端
- `sqlalchemy` - 数据库 ORM
- `fastapi` - API 框架

需要在 requirements.txt 中添加:
```
prometheus_client==0.19.0
```

## 环境变量

```bash
# 必需
ACCOUNT_MONITOR_ENABLED=true               # 启用账号监控
ALERT_SCHEDULER_ENABLED=true               # 启用告警调度器

# 可选
ACCOUNT_MONITOR_METRICS_PORT=9091          # Prometheus metrics 端口
ACCOUNT_MONITOR_COLLECTION_INTERVAL=60     # 数据收集间隔（秒）
ACCOUNT_MONITOR_HISTORY_RETENTION_HOURS=24 # 历史数据保留时长（小时）
ALERT_SCHEDULER_CHECK_INTERVAL=60          # 告警检查间隔（秒）
ALERT_RULES_PATH=config/alert_rules.json   # 告警规则配置文件路径
```

## 注意事项

1. **端口冲突**: 确保 9091 端口未被占用
2. **Prometheus 集成**: 需要配置 Prometheus scrape 目标
3. **告警通知**: 当前告警仅记录日志，需要集成实际通知系统（邮件、Slack等）
4. **性能影响**: 监控数据收集会增加一定负载，建议根据账号数量调整收集间隔
5. **条件评估**: 当前使用简单 eval，生产环境建议使用更安全的表达式解析器

## 验证结果

- ✅ Prometheus metrics 正常暴露
- ✅ API 端点功能正常
- ✅ 告警规则配置正确
- ✅ 告警触发机制正常
- ✅ 告警冷却机制正常
- ✅ 告警解析机制正常
- ✅ 配置项生效

## 结论

P1-20 任务已完成，满足验收标准"指标可 scrape + 告警规则"。

**生成时间**: 2026-05-20
**生成者**: Devin
**任务状态**: ✅ 已完成