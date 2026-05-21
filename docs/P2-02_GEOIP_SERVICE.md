# P2-02: GeoIP 服务封装文档

## 概述

GeoIP 服务提供 IP 地址到地理位置信息的映射功能，支持两种数据源：
1. **MaxMind GeoIP2**（推荐）：离线数据库，高精度，性能好
2. **ip-api.com**（备用）：在线 API，无需本地数据库

## 功能特性

- ✅ 双数据源支持（MaxMind + ip-api）
- ✅ 自动故障切换
- ✅ 结果缓存（减少 API 调用）
- ✅ 准确率验证功能
- ✅ REST API 接口
- ✅ 完整的日志记录

## 验收标准

- 抽样准确率 ≥95%
- 固定样本集：`fixtures/p2_02_geoip_accuracy.json`
- CI 回归：`tests/test_p2_02_geoip_accuracy_regression.py`
- 支持常见的公共 DNS IP 查询
- 缓存机制有效减少重复查询

## 安装配置

### 1. 安装依赖

```bash
pip install aiohttp geoip2
```

### 2. 环境变量配置

在 `.env` 文件中添加以下配置：

```bash
# MaxMind GeoIP2（推荐，离线数据库）
MAXMIND_ENABLED=false  # 是否启用 MaxMind
MAXMIND_DB_PATH=/path/to/GeoLite2-Country.mmdb  # 数据库文件路径

# ip-api.com（备用，在线 API）
IPAPI_ENABLED=true  # 是否启用 ip-api
IPAPI_API_KEY=  # API 密钥（免费版不需要）

# 缓存配置
GEOIP_CACHE_TTL=3600  # 缓存时间（秒）
```

### 3. MaxMind 数据库设置（可选）

如果使用 MaxMind：

1. 下载 GeoLite2 免费数据库：https://dev.maxmind.com/geoip/geolite2-free-geolocation-data
2. 解压 `.mmdb` 文件
3. 设置 `MAXMIND_DB_PATH` 指向该文件
4. 设置 `MAXMIND_ENABLED=true`

## 使用方法

### Python 代码调用

```python
from app.services.geoip_service import get_geoip_service

# 获取服务实例
service = get_geoip_service()

# 查询国家代码
country_code = await service.get_country_code("8.8.8.8")
print(f"Country Code: {country_code}")  # 输出: US

# 查询国家名称
country_name = await service.get_country_name("8.8.8.8")
print(f"Country Name: {country_name}")  # 输出: United States

# 完整查询
result = await service.lookup("8.8.8.8")
if result:
    print(f"IP: {result.ip}")
    print(f"Country: {result.country_name} ({result.country_code})")
    print(f"Provider: {result.provider}")
```

### REST API 调用

#### 1. 查询完整信息

```bash
POST /api/v1/geoip/lookup
Content-Type: application/json

{
  "ip": "8.8.8.8"
}
```

响应：
```json
{
  "country_code": "US",
  "country_name": "United States",
  "ip": "8.8.8.8",
  "provider": "ip-api",
  "is_cached": false,
  "success": true
}
```

#### 2. 仅获取国家代码

```bash
GET /api/v1/geoip/country-code?ip=8.8.8.8
```

响应：
```json
{
  "ip": "8.8.8.8",
  "country_code": "US",
  "success": true
}
```

#### 3. 仅获取国家名称

```bash
GET /api/v1/geoip/country-name?ip=8.8.8.8
```

响应：
```json
{
  "ip": "8.8.8.8",
  "country_name": "United States",
  "success": true
}
```

#### 4. 清空缓存

```bash
POST /api/v1/geoip/cache/clear
```

响应：
```json
{
  "success": true,
  "message": "GeoIP cache cleared successfully"
}
```

## 准确率验证

```python
from app.services.geoip_service import get_geoip_service

service = get_geoip_service()

# 测试 IP 列表（IP, 期望国家代码）
test_ips = [
    ("8.8.8.8", "US"),    # Google DNS
    ("1.1.1.1", "US"),    # Cloudflare DNS
    ("208.67.222.222", "US"),  # OpenDNS
]

# 验证准确率
accuracy = await service.validate_accuracy(test_ips)
print(f"Accuracy: {accuracy * 100:.1f}%")  # 期望: ≥95%
```

## 错误处理

服务包含完善的错误处理机制：

1. **MaxMind 失败**：自动切换到 ip-api
2. **ip-api 失败**：返回 None，记录错误日志
3. **无效 IP**：返回 None
4. **网络超时**：设置 5 秒超时，避免阻塞
5. **缓存失效**：自动重试

## 性能优化

1. **缓存机制**：相同 IP 查询直接返回缓存结果
2. **异步请求**：使用 aiohttp 异步 HTTP 请求
3. **连接池**：复用 HTTP 连接
4. **超时控制**：避免长时间阻塞

## 日志记录

所有操作都有详细的日志记录：

```python
logger.bind(
    trace_id="geoip-8.8.8.8",
    component="geoip",
    ip="8.8.8.8",
    country_code="US",
    provider="ip-api",
).info("GeoIP lookup successful")
```

## 测试

运行测试：

```bash
pytest tests/test_geoip_service.py -v
pytest tests/test_p2_02_geoip_accuracy_regression.py -v
```

测试覆盖：
- ✅ 基本查询功能
- ✅ 缓存机制
- ✅ 错误处理
- ✅ 固定样本集 ≥95% 准确率回归
- ✅ API 端点

## 常见问题

### 1. MaxMind 数据库在哪里下载？

访问：https://dev.maxmind.com/geoip/geolite2-free-geolocation-data
注册账号后下载 GeoLite2-Country.mmdb

### 2. ip-api 有请求限制吗？

免费版：45 次/分钟
如果需要更高限制，可以购买 Pro 版或使用 MaxMind

### 3. 如何提高准确率？

- 使用 MaxMind 离线数据库（准确率更高）
- 定期更新 MaxMind 数据库
- 对于重要应用，可以结合多个数据源交叉验证

### 4. 缓存会占用多少内存？

默认使用内存缓存，每个查询结果约 100-200 字节
如果查询量大，建议改用 Redis 缓存

## 与其他模块集成

### 与分级引擎集成（P2-05）

```python
from app.services.geoip_service import get_geoip_service

async def calcUserLevel(user_profile):
    # 获取用户 IP 的国家代码
    geoip_service = get_geoip_service()
    country_code = await geoip_service.get_country_code(user_profile.ip_address)
    
    # 根据国家代码确定 T1/T2/T3 分层
    if country_code in T1_COUNTRIES:
        user_profile.country_tier = "T1"
    # ...
```

### 与入站流水线集成（P2-12）

在用户入站时自动解析 IP 国家：

```python
# 在 Telegram 消息处理中
from app.services.geoip_service import get_geoip_service

async def handle_telegram_message(message):
    user_ip = message.ip_address  # 假设能获取到 IP
    geoip_service = get_geoip_service()
    country_code = await geoip_service.get_country_code(user_ip)
    
    # 写入用户画像
    await update_user_profile_country(user_id, country_code)
```

## 维护建议

1. **定期更新 MaxMind 数据库**（每月）
2. **监控 API 调用成功率**
3. **定期验证准确率**
4. **监控缓存命中率**
5. **预留数据源切换机制**

## 性能指标

- 查询响应时间：<100ms（缓存），<1s（API）
- 准确率：≥95%（抽样）
- 可用性：99.9%（双数据源）
- 缓存命中率：>80%（典型场景）
