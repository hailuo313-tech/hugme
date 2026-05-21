# P5-04: 72小时 WebSocket 长稳压测

## 概述

P5-04 长稳压测对 WebSocket 连接进行 72 小时持续测试，验证系统在长时间运行下的稳定性，重点确保零消息丢失。验收标准为 0 丢消息。

## 测试目标

- ✅ 验证 WebSocket 连接在 72 小时内的稳定性
- ✅ 确保零消息丢失（ping/pong 机制验证）
- ✅ 监控连接断开和重连行为
- ✅ 测量系统正常运行时间
- ✅ 生成详细的稳定性报告
- ✅ 识别潜在的性能和稳定性问题

## 测试配置

### 默认配置
- **测试时长**: 72 小时
- **Ping 间隔**: 30 秒
- **报告间隔**: 1 小时
- **WebSocket URL**: `ws://127.0.0.1:8000/ws/operators/tasks`
- **验收标准**: 0 丢消息

### 环境变量
- `WS_URL`: WebSocket 端点 URL
- `OPERATOR_ID`: 测试操作员 ID
- `P5_04_TEST_DURATION_HOURS`: 测试时长（小时）
- `P5_04_PING_INTERVAL`: Ping 间隔（秒）
- `P5_04_REPORT_INTERVAL`: 报告间隔（秒）
- `P5_04_OUTPUT_DIR`: 报告输出目录

## 测试机制

### 连接稳定性测试
1. **连接建立**: 尝试建立 WebSocket 连接
2. **连接保持**: 维持连接并定期发送 ping
3. **断线重连**: 自动检测断线并尝试重连
4. **状态监控**: 记录连接状态变化

### 消息丢失检测
1. **Ping/Pong 机制**: 定期发送 ping，等待 pong 响应
2. **序列号跟踪**: 为每个消息分配序列号
3. **丢包计算**: 比较发送和接收的消息数量
4. **零丢失验证**: 确保所有 ping 都有对应的 pong 响应

### 监控指标
- **连接指标**: 连接成功率、重连次数、正常运行时间
- **消息指标**: 发送数量、接收数量、丢失数量、成功率
- **稳定性指标**: 正常运行时间百分比、平均会话时长

## 文件结构

```
E:/eris/
├── scripts/perf/
│   ├── p5_04_websocket_stability_test.py  # 长稳测试核心脚本
│   ├── run_p5_04_websocket_stability.sh    # 测试运行脚本
│   └── reports/                            # 稳定性报告输出目录
│       └── p5_04_websocket_stability_report_*.json
├── .github/workflows/
│   └── websocket-stability.yml            # CI 长稳测试配置
└── docs/
    └── P5-04_WEBSOCKET_STABILITY.md       # 本文档
```

## 本地运行

### 前置条件
1. Docker 和 Docker Compose 已安装
2. 项目服务正在运行：`docker compose up -d postgres redis api`
3. Python 3.12+ 和 websockets 库已安装

### 安装依赖
```bash
pip install websockets
```

### 运行方式

#### 方式 1：完整 72 小时测试（推荐用于生产验证）
```bash
# 使用默认配置（72 小时）
bash scripts/perf/run_p5_04_websocket_stability.sh

# 自定义配置
WS_URL=ws://127.0.0.1:8000/ws/operators/tasks \
OPERATOR_ID=my_test_operator \
TEST_DURATION_HOURS=72 \
bash scripts/perf/run_p5_04_websocket_stability.sh
```

#### 方式 2：快速验证测试（1 小时）
```bash
# 运行 1 小时快速测试
bash scripts/perf/run_p5_04_websocket_stability.sh --short-test

# 或手动设置短时长
TEST_DURATION_HOURS=1 \
REPORT_INTERVAL=600 \
bash scripts/perf/run_p5_04_websocket_stability.sh
```

#### 方式 3：直接使用 Python
```bash
# 设置环境变量
export WS_URL=ws://127.0.0.1:8000/ws/operators/tasks
export OPERATOR_ID=test_p5_04_operator
export P5_04_TEST_DURATION_HOURS=72
export P5_04_PING_INTERVAL=30
export P5_04_REPORT_INTERVAL=3600
export P5_04_OUTPUT_DIR=scripts/perf/reports

# 运行测试
python3 scripts/perf/p5_04_websocket_stability_test.py
```

#### 方式 4：仅检查环境
```bash
bash scripts/perf/run_p5_04_websocket_stability.sh --check-only
```

#### 方式 5：仅查看最新报告
```bash
bash scripts/perf/run_p5_04_websocket_stability.sh --report-only
```

## 稳定性报告

### 报告结构
测试完成后会生成 JSON 格式的稳定性报告，包含以下信息：

```json
{
  "report": {
    "test_start_time": "2026-05-21T00:00:00",
    "test_end_time": "2026-05-24T00:00:00",
    "duration_hours": 72.0,
    "operator_id": "test_p5_04_operator",
    "ws_url": "ws://127.0.0.1:8000/ws/operators/tasks",
    
    "connection_stats": {
      "connect_attempts": 1,
      "successful_connects": 1,
      "failed_connects": 0,
      "disconnect_count": 0,
      "reconnect_count": 0,
      "uptime_percentage": 100.0,
      "total_uptime_seconds": 259200.0,
      "total_downtime_seconds": 0.0
    },
    
    "message_stats": {
      "sent_count": 8640,
      "received_count": 8640,
      "lost_count": 0,
      "ping_sent": 8640,
      "ping_received": 8640,
      "ping_failed": 0,
      "ping_success_rate": 100.0
    },
    
    "uptime_percentage": 100.0,
    "reconnect_count": 0,
    "ping_success_rate": 100.0,
    
    "zero_message_loss": true,
    "message_loss_details": "Sent: 8640, Received: 8640, Lost: 0",
    
    "recommendations": [
      "✅ Zero message loss achieved"
    ]
  },
  
  "raw_stats": {
    "message_stats": {...},
    "connection_stats": {...},
    "ping_stats": {...}
  }
}
```

### 关键指标说明

#### 连接指标
- **连接成功率**: 成功连接次数 / 总连接尝试次数
- **重连次数**: 连接断开后重新连接的次数
- **正常运行时间百分比**: 正常运行时间 / 总测试时间
- **总停机时间**: 连接不可用的总时间

#### 消息指标
- **发送数量**: 发送的总消息数（主要是 ping）
- **接收数量**: 接收的总消息数（主要是 pong）
- **丢失数量**: 发送但未接收的消息数
- **Ping 成功率**: 接收到的 pong / 发送的 ping

#### 验收标准
- **零消息丢失**: 所有 ping 都有对应的 pong 响应
- **高可用性**: 正常运行时间 ≥ 99.9%
- **低重连率**: 重连次数 ≤ 5（72 小时内）

## CI 集成

### GitHub Actions 配置

长稳测试已集成到 `.github/workflows/websocket-stability.yml`：

```yaml
name: WebSocket Stability Test

on:
  workflow_dispatch:
    inputs:
      duration_hours:
        default: '1'  # CI 默认 1 小时
  schedule:
    # 每周一 00:00 UTC 运行 1 小时冒烟测试
    - cron: '0 0 * * 1'
```

### 执行方式
1. **手动触发**: 通过 GitHub Actions 界面手动触发，可自定义时长
2. **定时冒烟**: 每周一自动执行 1 小时测试

### CI vs 生产测试
- **CI 环境**: 1 小时冒烟测试，快速验证基本功能
- **生产环境**: 72 小时完整测试，验证长时稳定性

### CI 环境配置
- `LLM_ECHO_FALLBACK=1`: 使用回退模式
- `CONTENT_SAFETY_ENABLED=0`: 禁用内容安全检查
- `SCORE_WORKER_ENABLED=0`: 禁用评分 worker
- `POLICY_HANDOFF_ENABLED=0`: 禁用策略交接

## 生产环境部署建议

### 专用测试环境
对于 72 小时生产级长稳测试，建议：

1. **独立服务器**: 使用专用的测试服务器
2. **生产配置**: 使用与生产相同的配置
3. **监控集成**: 集成到现有监控系统（Prometheus/Grafana）
4. **告警配置**: 配置异常情况告警
5. **日志收集**: 集中收集和分析日志

### 后台运行
```bash
# 使用 nohup 后台运行
nohup bash scripts/perf/run_p5_04_websocket_stability.sh > stability_test.log 2>&1 &

# 使用 screen/tmux
screen -S stability_test
bash scripts/perf/run_p5_04_websocket_stability.sh
# Ctrl+A+D 分离会话

# 使用 systemd service（推荐）
# 创建 systemd service 文件
sudo systemctl start websocket-stability-test
sudo systemctl enable websocket-stability-test
```

### 监控和告警
建议配置以下监控和告警：
- **连接断开告警**: 连接断开超过 1 分钟
- **消息丢失告警**: 检测到任何消息丢失
- **高重连率告警**: 1 小时内重连超过 5 次
- **服务不可用告警**: WebSocket 端点无响应

## 故障排查

### 常见问题

#### 1. 连接失败
```
❌ Connection failed: [Errno 111] Connection refused
```
**解决方案**:
- 检查 API 服务状态: `docker compose ps`
- 查看服务日志: `docker compose logs api`
- 验证 WebSocket 端点配置
- 检查防火墙设置

#### 2. 频繁断线重连
```
❌ High reconnect count: 15
```
**解决方案**:
- 检查网络稳定性
- 查看服务器资源使用情况
- 检查 WebSocket 超时配置
- 分析断线时间模式

#### 3. 消息丢失
```
❌ Message loss detected: Sent: 100, Received: 95, Lost: 5
```
**解决方案**:
- 检查网络延迟和丢包率
- 分析服务器负载情况
- 检查 WebSocket 缓冲区配置
- 优化 ping 间隔

#### 4. 内存泄漏
```
MemoryError: Unable to allocate memory
```
**解决方案**:
- 监控内存使用情况
- 优化消息队列大小
- 实现定期报告清理
- 增加系统内存

#### 5. 测试中断
```
⚠️ Test interrupted by user
```
**解决方案**:
- 使用后台运行方式
- 配置自动重启机制
- 实现断点续传功能
- 添加异常恢复逻辑

## 性能基准

### 稳定性等级
| 等级 | 正常运行时间 | 重连次数 | 说明 |
|------|-------------|----------|------|
| 优秀 | ≥ 99.99% | 0 | 完美稳定性 |
| 良好 | ≥ 99.9% | ≤ 2 | 高稳定性 |
| 合格 | ≥ 99.0% | ≤ 5 | 满足验收标准 |
| 需优化 | 95-99% | 5-10 | 需要稳定性优化 |
| 不可接受 | < 95% | > 10 | 必须优化 |

### 消息丢失标准
| 等级 | 消息丢失率 | 说明 |
|------|-----------|------|
| 优秀 | 0% | 零丢失（验收标准） |
| 良好 | < 0.01% | 极低丢失率 |
| 合格 | < 0.1% | 可接受丢失率 |
| 需优化 | 0.1-1% | 需要优化 |
| 不可接受 | > 1% | 必须优化 |

## 优化建议

### 连接稳定性优化
- 实现心跳机制优化
- 增加重试退避策略
- 优化连接超时设置
- 实现连接池管理

### 消息可靠性优化
- 实现消息确认机制
- 添加消息重传逻辑
- 优化消息队列管理
- 实现消息持久化

### 系统资源优化
- 优化内存使用
- 实现连接数限制
- 优化 CPU 使用率
- 实现资源监控和自适应

### 网络优化
- 实现网络质量检测
- 优化网络缓冲区设置
- 实现多路径冗余
- 优化网络协议栈

## 监控集成

### Prometheus 集成
建议添加以下监控指标：
```python
# 示例 Prometheus 指标
from prometheus_client import Counter, Histogram, Gauge

websocket_connections_total = Counter('websocket_connections_total', 'Total WebSocket connections')
websocket_reconnects_total = Counter('websocket_reconnects_total', 'Total WebSocket reconnections')
websocket_messages_sent = Counter('websocket_messages_sent', 'Total messages sent')
websocket_messages_received = Counter('websocket_messages_received', 'Total messages received')
websocket_connection_duration = Histogram('websocket_connection_duration_seconds', 'WebSocket connection duration')
websocket_current_connections = Gauge('websocket_current_connections', 'Current WebSocket connections')
```

### Grafana 仪表板
建议创建 Grafana 仪表板显示：
- 实时连接数
- 消息发送/接收速率
- 连接成功率
- 重连次数趋势
- 系统资源使用

## 最佳实践

### 测试前
1. 确保测试环境与生产环境配置相似
2. 准备监控和告警系统
3. 预留足够的系统资源
4. 通知相关人员测试时间
5. 准备回滚方案

### 测试中
1. 实时监控关键指标
2. 定期检查报告生成
3. 记录异常情况
4. 保持测试环境稳定
5. 避免在生产高峰期进行测试

### 测试后
1. 分析完整测试报告
2. 识别稳定性问题
3. 制定优化计划
4. 验证优化效果
5. 更新稳定性基线

## 扩展功能

### 多并发连接测试
修改脚本以支持多个并发 WebSocket 连接：
```python
async def run_multiple_connections(num_connections=10):
    tasks = [WebSocketStabilityTester(...) for _ in range(num_connections)]
    await asyncio.gather(*[task.run_test() for task in tasks])
```

### 自定义消息类型测试
扩展脚本以支持不同类型的消息：
- 任务消息（task.upsert, task.removed）
- 用户升级消息（user.upgraded）
- 自定义业务消息

### 压力测试
在长稳测试基础上增加压力：
- 增加消息发送频率
- 增加并发连接数
- 模拟网络抖动
- 模拟服务器负载

## 相关文档

- [WebSocket 协议文档](../D5-4_WEBSOCKET_PROTOCOL.md)
- [WebSocket 协议规范](../docs/ws_protocol.md)
- [P5-02 并发压测文档](P5-02_LOAD_TESTING.md)
- [系统监控文档](../monitoring/)

## 验收标准

✅ **零消息丢失**: 72 小时内无任何消息丢失  
✅ **高可用性**: 正常运行时间 ≥ 99.9%  
✅ **低重连率**: 重连次数 ≤ 5（72 小时内）  
✅ **完整报告**: 生成详细的稳定性报告  
✅ **CI 集成**: 支持自动化冒烟测试  

## 版本历史

- **v1.0** (2026-05-21): 初始版本
  - 实现 72 小时 WebSocket 长稳测试
  - 零消息丢失检测机制
  - 自动化报告生成
  - CI 集成（1 小时冒烟测试）

## 联系方式

如有问题或建议，请联系开发团队或提交 Issue。