# P5-02: 1000 并发压测 + P99 报告

## 概述

P5-02 压测任务对 ERIS API 进行 1000 并发请求的性能测试，生成详细的性能报告，重点关注 P99 延迟指标。验收标准为 P99 < 500ms。

## 测试目标

- ✅ 验证系统在 1000 并发下的稳定性
- ✅ 测量关键 API 端点的 P99 延迟
- ✅ 生成详细的性能报告
- ✅ 确保系统在高负载下保持可用性
- ✅ 识别性能瓶颈和优化机会

## 测试配置

### 默认配置
- **并发数**: 1000
- **每端点请求数**: 10
- **总请求数**: 30,000 (3 个端点 × 1000 并发 × 10 请求)
- **超时时间**: 30 秒
- **验收标准**: P99 < 500ms

### 测试端点
1. `GET /health` - 健康检查端点
2. `GET /health/detail` - 详细健康检查端点
3. `POST /telegram/webhook` - Telegram webhook 端点

### 环境变量
- `API_BASE`: API 基础 URL (默认: `http://127.0.0.1:8000`)
- `P5_02_CONCURRENCY`: 并发数 (默认: `1000`)
- `P5_02_REQUESTS_PER_ENDPOINT`: 每端点请求数 (默认: `10`)
- `P5_02_TIMEOUT_SECONDS`: 超时时间 (默认: `30`)
- `P5_02_OUTPUT_DIR`: 报告输出目录 (默认: `scripts/perf/reports`)

## 文件结构

```
E:/eris/
├── scripts/perf/
│   ├── p5_02_load_test.py           # 压测核心脚本
│   ├── run_p5_02_load_test.sh       # 压测运行脚本
│   └── reports/                     # 性能报告输出目录
│       └── p5_02_load_test_report_*.json
├── .github/workflows/
│   └── load-testing.yml             # CI 压测配置
└── docs/
    └── P5-02_LOAD_TESTING.md        # 本文档
```

## 本地运行

### 前置条件
1. Docker 和 Docker Compose 已安装
2. 项目服务正在运行：`docker compose up -d postgres redis api`
3. Python 3.12+ 已安装

### 运行方式

#### 方式 1：使用 Shell 脚本（推荐）
```bash
# 使用默认配置
bash scripts/perf/run_p5_02_load_test.sh

# 自定义配置
API_BASE=http://127.0.0.1:8000 \
CONCURRENCY=500 \
REQUESTS_PER_ENDPOINT=5 \
bash scripts/perf/run_p5_02_load_test.sh

# 仅检查环境
bash scripts/perf/run_p5_02_load_test.sh --check-only

# 仅显示最新报告
bash scripts/perf/run_p5_02_load_test.sh --report-only
```

#### 方式 2：直接使用 Python
```bash
# 设置环境变量
export API_BASE=http://127.0.0.1:8000
export P5_02_CONCURRENCY=1000
export P5_02_REQUESTS_PER_ENDPOINT=10
export P5_02_TIMEOUT_SECONDS=30
export P5_02_OUTPUT_DIR=scripts/perf/reports

# 运行压测
python3 scripts/perf/p5_02_load_test.py
```

## 性能报告

### 报告结构
压测完成后会生成 JSON 格式的性能报告，包含以下信息：

```json
{
  "test_summary": {
    "test_name": "P5-02 Load Test",
    "timestamp": "2026-05-21T00:00:00",
    "base_url": "http://127.0.0.1:8000",
    "concurrency": 1000,
    "requests_per_endpoint": 10,
    "total_endpoints": 3,
    "total_requests": 30000,
    "successful_requests": 29950,
    "failed_requests": 50,
    "overall_success_rate": 99.83,
    "acceptance_criteria": {
      "p99_threshold_ms": 500,
      "p99_actual_ms": 423.5,
      "passed": true
    }
  },
  "overall_latency_ms": {
    "min": 45.2,
    "p50": 123.4,
    "p75": 187.6,
    "p90": 245.8,
    "p95": 312.3,
    "p99": 423.5,
    "p99_9": 487.2,
    "max": 498.7,
    "mean": 156.8,
    "std": 67.3
  },
  "endpoint_statistics": [
    {
      "endpoint": "/health",
      "method": "GET",
      "total_requests": 10000,
      "successful_requests": 9980,
      "failed_requests": 20,
      "success_rate": 99.80,
      "latency_ms": {
        "min": 45.2,
        "p50": 98.3,
        "p95": 156.7,
        "p99": 234.5,
        "max": 298.3,
        "mean": 112.4,
        "std": 45.6
      },
      "errors": []
    }
  ],
  "recommendations": [
    "✅ P99 latency 423.5ms meets 500ms threshold",
    "✅ All performance metrics are within acceptable ranges"
  ]
}
```

### 关键指标说明

#### 延迟百分位
- **P50**: 中位数延迟，50% 的请求低于此值
- **P95**: 95% 的请求低于此值
- **P99**: 99% 的请求低于此值（关键指标）
- **P99.9**: 99.9% 的请求低于此值

#### 其他指标
- **成功率**: 请求成功的百分比
- **标准差**: 延迟的波动程度，高标准差表示性能不稳定
- **吞吐量**: 单位时间处理的请求数

## CI 集成

### GitHub Actions 配置

压测已集成到 `.github/workflows/load-testing.yml`：

```yaml
name: Load Testing

on:
  workflow_dispatch:
    inputs:
      concurrency:
        description: 'Number of concurrent requests'
        default: '1000'
      requests_per_endpoint:
        description: 'Requests per endpoint'
        default: '10'
  schedule:
    # Weekly on Sunday at 00:00 UTC
    - cron: '0 0 * * 0'
```

### 执行方式
1. **手动触发**: 通过 GitHub Actions 界面手动触发，可自定义参数
2. **定时执行**: 每周日 UTC 00:00 自动执行

### CI 环境配置
- `LLM_ECHO_FALLBACK=1`: 使用回退模式
- `CONTENT_SAFETY_ENABLED=0`: 禁用内容安全检查
- `SCORE_WORKER_ENABLED=0`: 禁用评分 worker
- `POLICY_HANDOFF_ENABLED=0`: 禁用策略交接

### 报告存储
- 压测报告自动上传为 GitHub Actions artifacts
- 保留 30 天
- 可从 Actions 运行页面下载

## 性能基准

### 验收标准
- **P99 延迟**: < 500ms
- **成功率**: > 99%
- **错误率**: < 1%

### 性能等级
| 等级 | P99 延迟 | 说明 |
|------|----------|------|
| 优秀 | < 200ms | 性能非常好 |
| 良好 | 200-350ms | 性能良好 |
| 合格 | 350-500ms | 满足验收标准 |
| 需优化 | 500-1000ms | 需要性能优化 |
| 不可接受 | > 1000ms | 必须优化 |

### 优化建议

#### 数据库优化
- 添加适当的索引
- 优化查询语句
- 使用连接池
- 考虑读写分离

#### 缓存优化
- 实现 Redis 缓存
- 缓存热点数据
- 设置合理的过期时间

#### 应用优化
- 异步处理非关键路径
- 优化算法复杂度
- 减少不必要的计算
- 使用更高效的数据结构

#### 基础设施优化
- 增加服务器资源
- 使用负载均衡
- CDN 加速静态资源
- 优化网络配置

## 故障排查

### 常见问题

#### 1. 连接被拒绝
```
[ERROR] API is not accessible within timeout
```
**解决方案**:
- 检查服务状态: `docker compose ps`
- 查看日志: `docker compose logs api`
- 手动测试: `curl http://127.0.0.1:8000/health`

#### 2. 高超时率
```
❌ Failed requests: 500+
```
**解决方案**:
- 增加超时时间
- 检查系统资源使用情况
- 查看应用日志中的错误
- 考虑降低并发数

#### 3. P99 延迟过高
```
❌ P99 acceptance criteria failed: 650ms >= 500ms
```
**解决方案**:
- 分析慢查询
- 检查数据库连接池
- 查看系统资源瓶颈
- 优化应用代码

#### 4. 内存不足
```
MemoryError: Unable to allocate memory
```
**解决方案**:
- 降低并发数
- 减少每端点请求数
- 增加系统内存
- 优化内存使用

## 监控指标

### 实时监控
在压测过程中监控以下指标：
- CPU 使用率
- 内存使用率
- 网络带宽
- 磁盘 I/O
- 数据库连接数
- API 响应时间

### 监控工具
- **系统级**: `top`, `htop`, `iotop`
- **应用级**: 应用日志, 性能分析器
- **数据库**: `pg_stat_activity`, 慢查询日志
- **网络**: `iftop`, `nethogs`

## 最佳实践

### 压测前
1. 确保测试环境与生产环境配置相似
2. 准备足够的测试数据
3. 监控系统资源使用情况
4. 设置合理的超时和重试策略
5. 通知相关人员压测时间

### 压测中
1. 实时监控系统指标
2. 准备好回滚方案
3. 记录异常情况
4. 避免在生产环境高峰期进行压测

### 压测后
1. 分析性能报告
2. 识别性能瓶颈
3. 制定优化计划
4. 验证优化效果
5. 更新性能基线

## 扩展功能

### 添加新端点
在 `scripts/perf/p5_02_load_test.py` 中的 `ENDPOINTS` 列表添加新端点：

```python
ENDPOINTS = [
    ("GET", "/health"),
    ("POST", "/api/v1/users"),
    # 添加新端点
    ("GET", "/api/v1/conversations"),
]
```

### 自定义负载模式
修改并发和请求数来模拟不同的负载模式：
- **突发负载**: 高并发，短时间
- **持续负载**: 中等并发，长时间
- **渐进负载**: 从低到高逐步增加

### 分布式压测
对于更大规模的压测，可以考虑：
- 使用多个压测客户端
- 使用云服务进行分布式压测
- 使用专业的压测工具如 JMeter、Gatling

## 相关文档

- [P5-01 E2E 测试文档](P5-01_E2E_MTPROTO_AI_ARCHIVE.md)
- [API 文档](../app/api/)
- [系统架构文档](../docs/)

## 验收标准

✅ **P99 < 500ms**: 关键 API 端点的 P99 延迟低于 500ms  
✅ **成功率 > 99%**: 请求成功率超过 99%  
✅ **系统稳定**: 压测过程中系统保持稳定，无崩溃  
✅ **报告完整**: 生成详细的性能报告  
✅ **CI 集成**: 压测集成到 CI/CD 流程  

## 版本历史

- **v1.0** (2026-05-21): 初始版本
  - 实现 1000 并发压测
  - P99 性能指标收集
  - 自动化报告生成
  - CI 集成

## 联系方式

如有问题或建议，请联系开发团队或提交 Issue。