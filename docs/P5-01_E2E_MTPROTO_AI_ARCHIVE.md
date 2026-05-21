# P5-01: E2E 测试 - MTProto 入站 → AI → 拟人投递 → 归档

## 概述

P5-01 E2E 测试验证完整的业务流程：从 MTProto 消息入站开始，经过 AI 处理，实现拟人化投递，最终完成对话归档。此测试确保系统各组件集成正确，数据流完整，符合业务要求。

## 测试目标

- ✅ 验证 MTProto 消息入站接收功能
- ✅ 验证 AI 处理流程（话术匹配 + LLM 编排）
- ✅ 验证拟人化投递（输入指示 + 延迟控制）
- ✅ 验证归档流程（script_hit 审计追踪）
- ✅ 验证端到端可追踪性（trace_id 链路）
- ✅ 确保在 CI nightly 环境中稳定运行

## 测试覆盖范围

### 1. MTProto 入站测试 (`test_01_mtproto_inbound_webhook`)
- 模拟 Telegram webhook 消息接收
- 验证用户和对话在数据库中的创建
- 确认消息正确入库并分配 trace_id

### 2. 话术匹配测试 (`test_02_script_matching_inbound`)
- 验证入站消息的 script_hit_id 记录
- 确认话术匹配引擎正常工作
- 检查审计追踪数据完整性

### 3. AI 处理测试 (`test_03_ai_processing_with_llm`)
- 发送后续消息触发 AI 处理
- 验证 LLM 编排和响应生成
- 确认出站消息正确创建

### 4. 拟人化投递测试 (`test_04_human_like_delivery`)
- 验证消息长度符合人类特征（10-200 字符）
- 检查消息发送延迟（非即时发送）
- 确认拟人化特征正常

### 5. 审计追踪测试 (`test_05_script_hit_audit_trail`)
- 验证 script_hits 表记录完整
- 确认每个消息都有对应的话术匹配记录
- 检查审计数据一致性

### 6. 归档流程测试 (`test_06_archiving_process`)
- 模拟对话结束场景
- 验证消息和 script_hit 完整性
- 确认归档数据可追溯

### 7. 端到端追踪测试 (`test_07_end_to_end_traceability`)
- 验证 trace_id 覆盖率 ≥ 80%
- 确认调试信息完整
- 检查链路追踪连续性

## 文件结构

```
E:/eris/
├── tests/
│   └── test_p5_01_e2e_mtproto_ai_archive.py  # 主测试文件
├── scripts/e2e/
│   └── run_p5_01.sh                         # 测试运行脚本
├── .github/workflows/
│   └── nightly-e2e-ci.yml                   # CI 配置（已更新）
└── docs/
    └── P5-01_E2E_MTPROTO_AI_ARCHIVE.md      # 本文档
```

## 本地运行

### 前置条件
1. Docker 和 Docker Compose 已安装
2. 项目服务正在运行：`docker compose up -d postgres redis api`
3. Python 3.12+ 和 pytest 已安装

### 运行方式

#### 方式 1：使用脚本（推荐）
```bash
# 设置环境变量
export API_BASE=http://127.0.0.1:8000
export DB_CONTAINER=eris-postgres

# 运行测试
bash scripts/e2e/run_p5_01.sh

# 跳过清理（用于调试）
bash scripts/e2e/run_p5_01.sh --skip-cleanup

# 仅清理测试数据
bash scripts/e2e/run_p5_01.sh --cleanup-only
```

#### 方式 2：直接使用 pytest
```bash
# 设置环境变量
export PYTHONPATH=app
export API_BASE=http://127.0.0.1:8000
export DB_CONTAINER=eris-postgres

# 运行所有测试
pytest tests/test_p5_01_e2e_mtproto_ai_archive.py -v -s

# 运行特定测试类
pytest tests/test_p5_01_e2e_mtproto_ai_archive.py::TestP501E2EMTProtoFlow -v -s

# 运行特定测试方法
pytest tests/test_p5_01_e2e_mtproto_ai_archive.py::TestP501E2EMTProtoFlow::test_01_mtproto_inbound_webhook -v -s
```

#### 方式 3：快速冒烟测试
```bash
# 运行快速冒烟测试
pytest tests/test_p5_01_e2e_mtproto_ai_archive.py::test_p5_01_e2e_smoke -v
```

## CI 集成

### GitHub Actions 配置

P5-01 E2E 测试已集成到 `.github/workflows/nightly-e2e-ci.yml`：

```yaml
p5-01-e2e:
  name: p5-01-e2e-mtproto-flow
  runs-on: ubuntu-latest
  timeout-minutes: 30
  needs: c12-audit
  steps:
    - uses: actions/checkout@v4
    - name: Start stack (postgres, redis, api)
      env:
        LLM_ECHO_FALLBACK: "1"
        CONTENT_SAFETY_ENABLED: "0"
        SCORE_WORKER_ENABLED: "0"
        POLICY_HANDOFF_ENABLED: "0"
      run: |
        docker compose up -d postgres redis
        docker compose up -d --build api
        # ... health check ...
    - name: Run P5-01 E2E tests
      env:
        API_BASE: http://127.0.0.1:8000
        DB_CONTAINER: eris-postgres
        PYTHONPATH: app
      run: bash scripts/e2e/run_p5_01.sh
    - name: Upload API logs on failure
      if: failure()
      run: docker compose logs api --tail 200
```

### 定时执行

- **频率**: 每天 UTC 06:00 执行
- **触发条件**: 
  - 定时任务（cron: `0 6 * * *`）
  - 手动触发（workflow_dispatch）
- **依赖**: 需要 `c12-audit` 任务通过

### 环境变量

CI 环境中的关键配置：
- `LLM_ECHO_FALLBACK=1`: 使用回退模式，避免真实 LLM 调用
- `CONTENT_SAFETY_ENABLED=0`: 禁用内容安全检查
- `SCORE_WORKER_ENABLED=0`: 禁用评分 worker
- `POLICY_HANDOFF_ENABLED=0`: 禁用策略交接

## 测试数据管理

### 测试用户标识
- 用户 ID 格式: `test_p5_01_{timestamp}`
- 外部 ID 格式: `tg_test_p5_01_{timestamp}`
- 用户名格式: `p5_01_test_{user_id}`

### 数据清理
测试脚本会自动清理测试数据：
```sql
DELETE FROM users WHERE external_id LIKE 'tg_test_p5_01_%' OR username LIKE 'p5_01_test_%';
```

## 故障排查

### 常见问题

#### 1. API 未就绪
```
[ERROR] API did not become healthy within timeout
```
**解决方案**: 
- 检查服务状态: `docker compose ps`
- 查看日志: `docker compose logs api`
- 手动健康检查: `curl http://127.0.0.1:8000/health/detail`

#### 2. 数据库连接失败
```
[ERROR] Database container eris-postgres is not running
```
**解决方案**:
- 启动数据库: `docker compose up -d postgres`
- 检查容器状态: `docker ps`

#### 3. 话术模板缺失
```
[WARNING] No active script templates found
```
**解决方案**:
- 检查话术模板: 
  ```sql
  SELECT COUNT(*) FROM script_templates WHERE is_active = true;
  ```
- 如需要，运行种子数据脚本

#### 4. 测试超时
```
[ERROR] Test timeout after 30 seconds
```
**解决方案**:
- 检查系统性能
- 增加超时时间（修改脚本中的 timeout 设置）
- 查看是否有死锁或资源竞争

## 性能指标

### 预期性能
- API 健康检查: < 5 秒
- Webhook 响应: < 2 秒
- AI 处理延迟: < 5 秒（回退模式）
- 完整测试执行: < 3 分钟

### 监控指标
- 消息处理成功率: ≥ 95%
- trace_id 覆盖率: ≥ 80%
- 话术匹配成功率: ≥ 90%
- 端到端测试通过率: 100%（目标）

## 维护指南

### 添加新测试
1. 在 `TestP501E2EMTProtoFlow` 类中添加新测试方法
2. 遵循命名约定: `test_nn_description`
3. 使用 `setup_test_environment` fixture
4. 更新本文档的测试覆盖范围

### 修改测试数据
- 编辑测试文件中的 `TEST_USER_ID` 生成逻辑
- 更新清理 SQL 语句
- 确保数据唯一性

### 更新 CI 配置
- 修改 `.github/workflows/nightly-e2e-ci.yml`
- 调整超时时间和环境变量
- 测试配置变更

## 相关文档

- [C-12 E2E CI Review](C12_E2E_CI_REVIEW.md)
- [WebSocket 协议文档](ws_protocol.md)
- [业务流程文档](product/business-flow.html)

## 验收标准

✅ **CI nightly 绿**: P5-01 E2E 测试在 nightly CI 中稳定通过  
✅ **完整流程覆盖**: MTProto 入站 → AI → 拟人投递 → 归档  
✅ **数据完整性**: 所有消息都有 trace_id 和 script_hit_id  
✅ **性能达标**: 测试在 3 分钟内完成  
✅ **可维护性**: 测试代码清晰，易于扩展  

## 版本历史

- **v1.0** (2026-05-21): 初始版本，实现基础 E2E 测试流程
  - MTProto 入站验证
  - AI 处理验证
  - 拟人化投递验证
  - 归档流程验证
  - CI nightly 集成

## 联系方式

如有问题或建议，请联系开发团队或提交 Issue。