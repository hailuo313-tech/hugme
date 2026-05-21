# ERIS 运维手册 (RUNBOOK.md)

## 文档信息
- **版本**: v1.0
- **最后更新**: 2026-05-21
- **维护团队**: ERIS DevOps Team
- **适用环境**: Production / Staging / Development

## 文档目的
本运维手册提供 ERIS 系统的完整运维指南，包括系统架构、部署流程、监控告警、故障排查、备份恢复、应急响应等关键运维操作，确保系统稳定可靠运行。

---

## 目录
1. [系统架构](#1-系统架构)
2. [部署流程](#2-部署流程)
3. [监控和告警](#3-监控和告警)
4. [故障排查](#4-故障排查)
5. [备份和恢复](#5-备份和恢复)
6. [应急响应](#6-应急响应)
7. [性能优化](#7-性能优化)
8. [安全最佳实践](#8-安全最佳实践)
9. [日常运维](#9-日常运维)
10. [演练场景](#10-演练场景)

---

## 1. 系统架构

### 1.1 整体架构
```
┌─────────────────────────────────────────────────────────────┐
│                      用户层 (Users)                          │
│  Telegram 真人用户 | H5 网页用户 | 移动 App 用户           │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                      接入层 (Ingress)                        │
│  MTProto 接入 | WebSocket 服务 | HTTP API                 │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                   应用层 (Application)                       │
│  FastAPI 服务 (eris-api)                                    │
│  - 业务逻辑处理                                             │
│  - AI 处理 (LLM Orchestrator)                               │
│  - 消息队列处理                                             │
│  - WebSocket 管理                                           │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                   数据层 (Data)                              │
│  PostgreSQL (主数据库) | Redis (缓存)                      │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                  监控层 (Monitoring)                         │
│  Prometheus | Grafana | Node Exporter | Exporters          │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 核心组件

#### 应用服务
- **eris-api**: FastAPI 主应用服务
  - 端口: 8000
  - 职责: 业务逻辑处理、API 服务、WebSocket 服务
  - 健康检查: `/health`

#### 数据库服务
- **PostgreSQL**: 主数据库
  - 端口: 5432
  - 版本: pgvector/pgvector:pg16
  - 数据库: eris
  - 备份: 每日自动备份

- **Redis**: 缓存服务
  - 端口: 6379
  - 版本: 7-alpine
  - 用途: 缓存、会话管理、消息队列

#### 监控服务
- **Prometheus**: 指标收集和存储
  - 端口: 9090
  - 数据保留: 30天

- **Grafana**: 可视化面板
  - 端口: 3000
  - 认证: admin/admin (生产环境需修改)

- **Node Exporter**: 系统指标收集
  - 端口: 9100

- **PostgreSQL Exporter**: 数据库指标
  - 端口: 9187

- **Redis Exporter**: 缓存指标
  - 端口: 9121

### 1.3 网络架构
- **内部网络**: Docker 内部网络，服务间通信
- **外部访问**: 通过反向代理暴露必要端口
- **安全组**: 仅开放必要端口 (80, 443, 22)

### 1.4 数据流
1. **用户消息**: Telegram → MTProto → API → 业务处理 → AI → 响应
2. **WebSocket 连接**: 客户端 → WebSocket → 实时消息处理
3. **数据持久化**: 应用 → PostgreSQL/Redis
4. **监控数据**: 应用/系统 → Exporters → Prometheus → Grafana

---

## 2. 部署流程

### 2.1 环境准备

#### 服务器要求
- **CPU**: 4核心以上
- **内存**: 8GB 以上
- **磁盘**: 100GB 以上 SSD
- **操作系统**: Ubuntu 20.04+ / CentOS 7+
- **网络**: 稳定的互联网连接

#### 软件依赖
```bash
# Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Git
sudo apt update
sudo apt install git -y
```

### 2.2 代码部署

#### 克隆代码仓库
```bash
cd /opt
git clone https://github.com/hailuo313-tech/hugme.git eris
cd eris
```

#### 配置环境变量
```bash
# 创建 .env 文件
cat > .env <<EOF
POSTGRES_DB=eris
POSTGRES_USER=eris
POSTGRES_PASSWORD=your_secure_password
POSTGRES_MIGRATION_USER=eris_migration
POSTGRES_MIGRATION_PASSWORD=your_migration_password
POSTGRES_WRITER_USER=eris_writer
POSTGRES_WRITER_PASSWORD=your_writer_password
POSTGRES_READER_USER=eris_reader
POSTGRES_READER_PASSWORD=your_reader_password

REDIS_PASSWORD=your_redis_password

SECRET_KEY=your_secret_key_here

OPENROUTER_API_KEY=your_openrouter_api_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_API_ID=your_telegram_api_id
TELEGRAM_API_HASH=your_telegram_api_hash
TELEGRAM_SESSION_FERNET_KEY=your_fernet_key

GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=your_grafana_password

ENV=production
EOF
```

#### 启动服务
```bash
# 构建并启动所有服务
docker compose up -d --build

# 查看服务状态
docker compose ps

# 查看日志
docker compose logs -f api
```

### 2.3 数据库迁移
```bash
# 运行数据库迁移
docker compose exec api python -m alembic upgrade head

# 验证迁移状态
docker compose exec api python -m alembic current
```

### 2.4 健康检查
```bash
# 检查 API 健康状态
curl http://localhost:8000/health

# 检查数据库连接
docker compose exec postgres pg_isready -U eris

# 检查 Redis 连接
docker compose exec redis redis-cli -a your_redis_password ping

# 检查监控服务
curl http://localhost:9090/api/v1/targets  # Prometheus
curl http://localhost:3000/api/health       # Grafana
```

### 2.5 回滚流程

#### 快速回滚
```bash
# 回滚到上一个版本
git pull origin main
git checkout <previous_commit_hash>
docker compose up -d --build

# 或者回滚到特定分支
git checkout <previous_branch>
docker compose up -d --build
```

#### 数据库回滚
```bash
# 回滚数据库迁移
docker compose exec api python -m alembic downgrade -1

# 回滚到特定版本
docker compose exec api python -m alembic downgrade <revision_id>
```

---

## 3. 监控和告警

### 3.1 监控指标

#### 业务指标
- **活跃用户数**: 实时在线用户数
- **转化率**: 付费转化率
- **消息处理量**: 每秒消息处理数
- **LLM 调用**: AI 模型调用次数和延迟
- **收入**: 实时收入统计

#### 系统指标
- **CPU 使用率**: 服务器 CPU 使用情况
- **内存使用率**: 内存占用情况
- **磁盘使用率**: 存储空间使用情况
- **网络流量**: 入站/出站网络流量

#### 应用指标
- **API 响应时间**: 请求响应延迟
- **错误率**: HTTP 错误率
- **WebSocket 连接数**: 实时连接数
- **消息队列深度**: 待处理消息数

### 3.2 Grafana 仪表板

#### 访问仪表板
1. 登录 Grafana: http://your-server:3000
2. 导航到 Dashboards → ERIS Monitoring
3. 选择相应仪表板

#### 关键仪表板
- **业务概览**: 关键业务指标和 KPI
- **LLM 性能**: AI 处理性能和成本
- **系统健康**: 应用健康状态
- **基础设施**: 系统资源使用情况
- **实时监控**: 实时运营状态
- **转化漏斗**: 付费转化分析

### 3.3 告警规则

#### 关键告警
- **API 宕机**: API 服务不可用
- **高错误率**: HTTP 5xx 错误率 > 5%
- **高延迟**: P95 响应时间 > 2s
- **队列积压**: 消息队列 > 1000
- **资源耗尽**: CPU/内存/磁盘 > 90%

#### 告警处理流程
1. **接收告警**: 通过 Prometheus Alertmanager
2. **评估严重性**: 根据告警级别确定响应优先级
3. **执行响应**: 按照故障排查流程处理
4. **记录处理**: 更新故障处理记录
5. **事后分析**: 总结经验教训

### 3.4 日志管理

#### 日志收集
```bash
# 查看应用日志
docker compose logs -f api

# 查看特定时间段日志
docker compose logs --since="2024-01-01T00:00:00" api

# 查看错误日志
docker compose logs api | grep ERROR
```

#### 日志分析
- **错误日志**: 关注 ERROR 和 CRITICAL 级别
- **性能日志**: 分析慢查询和延迟问题
- **业务日志**: 追踪业务流程和用户行为

---

## 4. 故障排查

### 4.1 常见问题

#### API 服务无法启动
**症状**: API 容器无法启动或频繁重启

**排查步骤**:
1. 检查容器日志: `docker compose logs api`
2. 检查端口占用: `netstat -tuln | grep 8000`
3. 检查数据库连接: `docker compose exec api python -c "from core.database import init_db; import asyncio; asyncio.run(init_db())"`
4. 检查环境变量: `docker compose config`

**解决方案**:
- 修复配置错误
- 释放端口占用
- 检查数据库连接参数
- 重启服务: `docker compose restart api`

#### 数据库连接失败
**症状**: 应用无法连接到数据库

**排查步骤**:
1. 检查数据库状态: `docker compose ps postgres`
2. 检查数据库日志: `docker compose logs postgres`
3. 测试连接: `docker compose exec postgres pg_isready -U eris`
4. 检查网络连接: `docker compose exec api ping postgres`

**解决方案**:
- 重启数据库: `docker compose restart postgres`
- 检查数据库凭证
- 检查网络配置
- 扩大数据库连接池

#### Redis 连接失败
**症状**: 缓存操作失败

**排查步骤**:
1. 检查 Redis 状态: `docker compose ps redis`
2. 检查 Redis 日志: `docker compose logs redis`
3. 测试连接: `docker compose exec redis redis-cli ping`
4. 检查内存使用: `docker compose exec redis redis-cli INFO memory`

**解决方案**:
- 重启 Redis: `docker compose restart redis`
- 检查 Redis 密码
- 清理 Redis 内存: `docker compose exec redis redis-cli FLUSHALL`
- 扩大 Redis 内存限制

#### LLM API 调用失败
**症状**: AI 处理功能异常

**排查步骤**:
1. 检查 API 密钥配置
2. 检查 OpenRouter API 状态
3. 查看应用日志中的 LLM 相关错误
4. 检查网络连接

**解决方案**:
- 更新 API 密钥
- 启用降级模式
- 检查 API 配额
- 实现重试机制

#### WebSocket 连接异常
**症状**: 实时连接不稳定

**排查步骤**:
1. 检查 WebSocket 日志
2. 检查网络连接稳定性
3. 查看连接数统计
4. 检查负载均衡配置

**解决方案**:
- 优化 WebSocket 配置
- 实现自动重连机制
- 扩展连接数限制
- 检查防火墙设置

### 4.2 性能问题

#### 响应时间慢
**排查步骤**:
1. 检查系统资源使用: `htop`
2. 查看慢查询日志
3. 分析数据库性能
4. 检查网络延迟

**解决方案**:
- 优化数据库查询
- 增加缓存命中率
- 扩展服务器资源
- 优化应用代码

#### 内存泄漏
**排查步骤**:
1. 监控内存使用趋势
2. 分析内存增长模式
3. 检查应用代码
4. 使用内存分析工具

**解决方案**:
- 重启应用服务
- 修复内存泄漏代码
- 优化内存使用
- 增加内存限制

### 4.3 紧急故障处理

#### 服务完全不可用
**处理流程**:
1. **立即响应**: 收到告警后 5 分钟内响应
2. **评估影响**: 确定影响范围和严重程度
3. **快速恢复**: 执行快速恢复措施
4. **根因分析**: 确定根本原因
5. **预防措施**: 制定预防措施

**快速恢复措施**:
- 重启服务: `docker compose restart`
- 回滚到稳定版本
- 切换到备用服务
- 扩展服务容量

---

## 5. 备份和恢复

### 5.1 备份策略

#### 数据库备份
```bash
# 每日自动备份
0 2 * * * docker compose exec postgres pg_dump -U eris eris > /backup/eris_$(date +\%Y\%m\%d).sql

# 手动备份
docker compose exec postgres pg_dump -U eris eris > backup.sql
```

#### Redis 备份
```bash
# Redis RDB 备份（配置在 redis.conf）
save 900 1
save 300 10
save 60 10000

# 手动备份
docker compose exec redis redis-cli BGSAVE
```

#### 配置文件备份
```bash
# 备份环境配置
cp .env .env.backup.$(date +%Y%m%d)

# 备份 Docker 配置
tar czf docker_config_backup_$(date +%Y%m%d).tar.gz docker-compose.yml .env
```

### 5.2 恢复流程

#### 数据库恢复
```bash
# 停止应用服务
docker compose stop api

# 恢复数据库
docker compose exec -T postgres psql -U eris eris < backup.sql

# 重启应用服务
docker compose start api
```

#### Redis 恢复
```bash
# 停止 Redis
docker compose stop redis

# 恢复 RDB 文件
cp dump.rdb /var/lib/redis/

# 重启 Redis
docker compose start redis
```

#### 配置恢复
```bash
# 恢复环境配置
cp .env.backup.20240101 .env

# 重启服务
docker compose restart
```

### 5.3 灾难恢复

#### 完整系统恢复
1. **准备新服务器**: 按照环境准备步骤配置新服务器
2. **恢复代码**: 克隆代码仓库
3. **恢复配置**: 恢复环境配置文件
4. **恢复数据**: 恢复数据库和 Redis 数据
5. **启动服务**: 启动所有服务
6. **验证恢复**: 执行健康检查和功能测试

#### 数据同步
- **主从复制**: 配置 PostgreSQL 主从复制
- **实时同步**: 使用 Redis 主从复制
- **定期同步**: 定期备份到异地存储

---

## 6. 应急响应

### 6.1 应急响应团队

#### 角色和职责
- **应急指挥官**: 负责整体协调和决策
- **技术负责人**: 负责技术问题解决
- **运维工程师**: 负责基础设施操作
- **业务负责人**: 负责业务影响评估

#### 联系方式
- **紧急电话**: [设置紧急联系电话]
- **Slack 频道**: #incidents
- **邮件列表**: incidents@eris.com

### 6.2 响应级别

#### P1 - 严重故障
- **定义**: 核心服务完全不可用
- **响应时间**: 15 分钟
- **解决时间**: 4 小时
- **示例**: API 宕机、数据库无法访问

#### P2 - 重要故障
- **定义**: 核心功能降级但部分可用
- **响应时间**: 30 分钟
- **解决时间**: 8 小时
- **示例**: 性能严重下降、部分功能不可用

#### P3 - 一般故障
- **定义**: 非核心功能受影响
- **响应时间**: 1 小时
- **解决时间**: 24 小时
- **示例**: 次要功能异常、性能轻微下降

### 6.3 应急流程

#### 故障发现和报告
1. **自动发现**: 监控系统自动检测和告警
2. **用户报告**: 用户反馈问题
3. **主动发现**: 运维人员主动检查发现

#### 故障响应流程
1. **接收告警**: 通过告警系统接收故障通知
2. **评估严重性**: 确定故障级别和影响范围
3. **启动响应**: 根据级别启动相应响应流程
4. **故障处理**: 按照故障排查流程处理
5. **恢复验证**: 验证服务恢复正常
6. **事后分析**: 进行根因分析和总结

#### 通信机制
- **内部通信**: 使用 Slack 进行团队沟通
- **外部通信**: 通过状态页面通知用户
- **定期更新**: 每 30 分钟更新故障处理进度

---

## 7. 性能优化

### 7.1 应用优化

#### 代码优化
- **异步处理**: 使用异步 I/O 提高并发能力
- **连接池**: 使用数据库连接池减少连接开销
- **缓存策略**: 合理使用缓存减少数据库压力
- **查询优化**: 优化数据库查询，添加必要索引

#### 配置优化
```python
# 数据库连接池配置
DATABASE_POOL_SIZE = 20
DATABASE_MAX_OVERFLOW = 10
DATABASE_POOL_TIMEOUT = 30

# Redis 连接配置
REDIS_CONNECTION_POOL_SIZE = 50
REDIS_SOCKET_TIMEOUT = 5
```

### 7.2 数据库优化

#### 索引优化
```sql
-- 创建常用查询索引
CREATE INDEX idx_users_created_at ON users(created_at);
CREATE INDEX idx_messages_user_id ON messages(user_id);
CREATE INDEX idx_conversations_status ON conversations(status);
```

#### 查询优化
- 避免全表扫描
- 使用合适的索引
- 优化 JOIN 操作
- 分页查询大数据集

#### 数据库配置
```ini
# postgresql.conf 优化
shared_buffers = 256MB
effective_cache_size = 1GB
maintenance_work_mem = 64MB
checkpoint_completion_target = 0.9
wal_buffers = 16MB
default_statistics_target = 100
random_page_cost = 1.1
effective_io_concurrency = 200
work_mem = 16MB
min_wal_size = 1GB
max_wal_size = 4GB
```

### 7.3 缓存优化

#### Redis 配置
```ini
# redis.conf 优化
maxmemory 512mb
maxmemory-policy allkeys-lru
save 900 1
save 300 10
save 60 10000
```

#### 缓存策略
- **热点数据**: 缓存访问频繁的数据
- **计算结果**: 缓存复杂计算结果
- **会话数据**: 缓存用户会话信息
- **过期策略**: 设置合理的过期时间

### 7.4 网络优化

#### 负载均衡
- 使用 Nginx 进行负载均衡
- 配置健康检查
- 实现会话保持

#### CDN 加速
- 静态资源使用 CDN
- 配置缓存策略
- 启用压缩传输

---

## 8. 安全最佳实践

### 8.1 访问控制

#### 服务器安全
- **SSH 访问**: 仅使用密钥认证，禁用密码登录
- **防火墙**: 配置 iptables 或 ufw
- **用户管理**: 创建专门的运维用户，禁用 root 直接登录

#### 应用安全
- **API 认证**: 实现完善的 API 认证机制
- **权限控制**: 基于角色的访问控制 (RBAC)
- **输入验证**: 严格验证所有用户输入
- **SQL 注入防护**: 使用参数化查询

### 8.2 数据安全

#### 数据加密
- **传输加密**: 使用 HTTPS/TLS 加密数据传输
- **存储加密**: 敏感数据加密存储
- **会话加密**: 使用加密的会话管理

#### 备份加密
- **备份加密**: 备份文件加密存储
- **传输加密**: 备份传输过程加密
- **访问控制**: 备份文件访问权限控制

### 8.3 密钥管理

#### 密钥存储
- **环境变量**: 使用环境变量存储密钥
- **密钥轮换**: 定期轮换密钥
- **密钥分发**: 安全的密钥分发机制

#### 密钥安全
- **不硬编码**: 不在代码中硬编码密钥
- **访问控制**: 限制密钥访问权限
- **审计日志**: 记录密钥使用情况

### 8.4 安全监控

#### 入侵检测
- **日志监控**: 监控异常登录和操作
- **行为分析**: 分析异常行为模式
- **实时告警**: 配置安全事件告警

#### 漏洞管理
- **定期扫描**: 定期进行安全漏洞扫描
- **及时修补**: 及时修补已知漏洞
- **依赖更新**: 定期更新依赖包

---

## 9. 日常运维

### 9.1 每日任务

#### 健康检查
```bash
# 每日健康检查脚本
#!/bin/bash
echo "=== 每日健康检查 $(date) ==="

# 检查服务状态
docker compose ps

# 检查 API 健康
curl -f http://localhost:8000/health || echo "API 健康检查失败"

# 检查磁盘空间
df -h | grep -E '(Filesystem|/dev/)'

# 检查内存使用
free -h

# 检查日志错误
docker compose logs --since="1d" api | grep ERROR | tail -20
```

#### 日志检查
- 检查错误日志
- 分析异常模式
- 监控性能指标

#### 备份验证
- 验证备份完整性
- 测试恢复流程
- 检查备份存储空间

### 9.2 每周任务

#### 系统更新
```bash
# 更新系统包
sudo apt update && sudo apt upgrade -y

# 更新 Docker
sudo apt-get update
sudo apt-get install docker-ce docker-ce-cli containerd.io
```

#### 性能分析
- 分析性能趋势
- 识别性能瓶颈
- 制定优化计划

#### 安全检查
- 检查安全日志
- 分析异常访问
- 更新安全规则

### 9.3 每月任务

#### 容量规划
- 分析资源使用趋势
- 预测未来需求
- 制定扩容计划

#### 灾难恢复演练
- 执行灾难恢复演练
- 验证备份恢复流程
- 更新应急响应计划

#### 文档更新
- 更新系统架构文档
- 更新故障处理记录
- 更新运维流程

---

## 10. 演练场景

### 10.1 演练目的
- 验证运维手册的有效性
- 提升团队应急响应能力
- 发现潜在问题和改进点
- 确保系统稳定性和可靠性

### 10.2 演练场景

#### 场景 1: API 服务宕机
**目标**: 验证 API 服务故障恢复流程

**步骤**:
1. 停止 API 服务: `docker compose stop api`
2. 模拟故障告警
3. 执行故障排查流程
4. 恢复 API 服务: `docker compose start api`
5. 验证服务恢复正常
6. 记录处理过程和改进建议

**验收标准**:
- 故障发现时间 < 5 分钟
- 故障恢复时间 < 15 分钟
- 服务完全恢复正常

#### 场景 2: 数据库故障
**目标**: 验证数据库故障切换和恢复流程

**步骤**:
1. 停止数据库服务: `docker compose stop postgres`
2. 模拟数据库故障告警
3. 执行数据库故障排查
4. 恢复数据库服务: `docker compose start postgres`
5. 验证数据完整性
6. 测试应用连接

**验收标准**:
- 故障发现时间 < 5 分钟
- 数据恢复时间 < 30 分钟
- 数据完整性验证通过

#### 场景 3: 高负载压力测试
**目标**: 验证系统在高负载下的表现

**步骤**:
1. 使用压力测试工具模拟高负载
2. 监控系统资源使用情况
3. 观察系统响应时间和错误率
4. 记录系统瓶颈
5. 制定性能优化建议

**验收标准**:
- 系统在负载下保持稳定
- 响应时间在可接受范围内
- 错误率低于阈值

#### 场景 4: 数据恢复演练
**目标**: 验证备份恢复流程的有效性

**步骤**:
1. 创建测试数据
2. 执行数据库备份
3. 删除部分数据
4. 执行数据恢复
5. 验证数据完整性
6. 记录恢复过程

**验收标准**:
- 备份过程顺利完成
- 数据恢复成功
- 数据完整性验证通过
- 恢复时间在预期范围内

#### 场景 5: 安全事件响应
**目标**: 验证安全事件响应流程

**步骤**:
1. 模拟安全事件（异常登录）
2. 触发安全告警
3. 执行安全事件响应流程
4. 分析安全日志
5. 采取相应安全措施
6. 更新安全策略

**验收标准**:
- 安全事件及时发现
- 响应流程执行正确
- 安全措施有效
- 事件记录完整

### 10.3 演练评估

#### 评估标准
- **响应时间**: 是否在规定时间内响应
- **处理效果**: 问题是否得到有效解决
- **团队协作**: 团队配合是否顺畅
- **文档完整性**: 文档是否准确完整
- **改进建议**: 是否有可行的改进建议

#### 演练报告
每次演练后需要提交演练报告，包括：
- 演练场景和目标
- 演练过程记录
- 发现的问题和改进点
- 团队表现评估
- 后续改进计划

### 10.4 演练频率
- **月度演练**: 每月进行一次小规模演练
- **季度演练**: 每季度进行一次全面演练
- **年度演练**: 每年进行一次大规模演练

---

## 附录

### A. 常用命令

#### Docker Compose 命令
```bash
# 启动所有服务
docker compose up -d

# 停止所有服务
docker compose down

# 重启特定服务
docker compose restart api

# 查看服务状态
docker compose ps

# 查看服务日志
docker compose logs -f api

# 进入服务容器
docker compose exec api bash
```

#### 数据库命令
```bash
# 连接数据库
docker compose exec postgres psql -U eris -d eris

# 备份数据库
docker compose exec postgres pg_dump -U eris eris > backup.sql

# 恢复数据库
docker compose exec -T postgres psql -U eris eris < backup.sql

# 查看数据库大小
docker compose exec postgres psql -U eris -c "SELECT pg_size_pretty(pg_database_size('eris'));"
```

#### Redis 命令
```bash
# 连接 Redis
docker compose exec redis redis-cli -a your_password

# 查看所有键
docker compose exec redis redis-cli -a your_password KEYS '*'

# 清空所有数据
docker compose exec redis redis-cli -a your_password FLUSHALL

# 查看 Redis 信息
docker compose exec redis redis-cli -a your_password INFO
```

### B. 联系方式

#### 运维团队
- **负责人**: [运维负责人姓名]
- **电话**: [运维负责人电话]
- **邮箱**: [运维负责人邮箱]

#### 应急联系
- **紧急电话**: [紧急联系电话]
- **Slack 频道**: #operations
- **邮件列表**: ops@eris.com

### C. 相关文档
- 系统架构文档: `docs/ARCHITECTURE.md`
- API 文档: `docs/API.md`
- 部署文档: `docs/DEPLOYMENT.md`
- 监控文档: `docs/P5-05_PROMETHEUS_MONITORING.md`
- Grafana 文档: `docs/P5-06_GRAFANA_DASHBOARDS.md`

### D. 版本历史
- **v1.0** (2026-05-21): 初始版本，包含完整的运维手册内容

---

**文档维护**: 本文档应随着系统演进定期更新，至少每季度评审一次。

**演练要求**: 按照本手册中的演练场景定期进行演练，确保运维团队熟练掌握应急响应流程。