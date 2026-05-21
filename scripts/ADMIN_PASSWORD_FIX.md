# 后台密码问题紧急修复指南

## 问题分析
密码无法登录的可能原因：
1. 数据库中没有创建管理员账号
2. 密码哈希不匹配
3. 数据库服务未启动
4. 数据库连接配置问题

## 快速修复方案

### 方案1: 使用Python脚本（推荐）

如果您有Python环境：

```bash
cd E:/eris
pip install asyncpg
python scripts/create_admin_direct.py
```

脚本会自动：
- 连接数据库
- 检查现有账号
- 创建或重置admin账号
- 密码设置为: `admin123`

### 方案2: 使用Docker（如果有Docker）

```bash
cd E:/eris
docker compose up -d postgres
docker compose exec postgres psql -U eris -d eris -c "
INSERT INTO operators (username, password_hash, display_name, role, status)
VALUES (
    'admin',
    '0192023a7bbd73250516f069df18b500',
    '系统管理员',
    'admin',
    'active'
) ON CONFLICT (username) DO UPDATE SET
password_hash = EXCLUDED.password_hash,
updated_at = NOW();
"
```

### 方案3: 使用数据库客户端工具

1. 使用pgAdmin、DBeaver或其他PostgreSQL客户端
2. 连接到数据库：
   - 主机: localhost
   - 端口: 5432
   - 用户: eris
   - 密码: eris_secret_2026 (或您的实际密码)
   - 数据库: eris
3. 执行SQL：

```sql
-- 删除现有admin账号（如果有）
DELETE FROM operators WHERE username = 'admin';

-- 创建新的admin账号
INSERT INTO operators (username, password_hash, display_name, role, status)
VALUES (
    'admin',
    '0192023a7bbd73250516f069df18b500',  -- admin123的SHA256哈希
    '系统管理员',
    'admin',
    'active'
);
```

### 方案4: 手动生成密码哈希

如果您想使用自定义密码：

```python
import hashlib

password = "your_custom_password"
password_hash = hashlib.sha256(password.encode()).hexdigest()
print(f"Password: {password}")
print(f"Hash: {password_hash}")
```

然后使用生成的哈希值执行SQL：

```sql
INSERT INTO operators (username, password_hash, display_name, role, status)
VALUES (
    'admin',
    '您的密码哈希值',
    '系统管理员',
    'admin',
    'active'
);
```

## Windows环境特别说明

### Docker Desktop未安装

1. 下载安装Docker Desktop for Windows:
   https://www.docker.com/products/docker-desktop/

2. 安装后启动Docker Desktop

3. 重新执行方案2的命令

### Docker命令不可用

如果Docker已安装但命令不可用：
1. 检查Docker Desktop是否正在运行
2. 重启命令提示符或PowerShell
3. 检查环境变量PATH是否包含Docker

### 直接使用PostgreSQL服务

如果您本地安装了PostgreSQL：

```bash
# 使用psql命令行工具
psql -U eris -d eris -h localhost -p 5432

# 然后执行SQL
```

## 验证修复

修复后，验证账号是否创建成功：

```sql
SELECT username, display_name, role, status FROM operators WHERE username = 'admin';
```

应该看到类似输出：
```
 username | display_name | role  | status 
----------+--------------+-------+--------
 admin    | 系统管理员   | admin | active
```

## 测试登录

1. 确保后端服务正在运行
2. 访问: `http://localhost:3000/admin`
3. 使用凭据登录：
   - 用户名: `admin`
   - 密码: `admin123`

## 仍然无法登录？

如果以上方法都无法解决，请检查：

1. **后端服务状态**:
```bash
cd E:/eris
docker compose ps
docker compose logs api
```

2. **数据库连接**:
- 确认PostgreSQL正在运行
- 确认连接配置正确
- 确认用户权限足够

3. **前端配置**:
- 确认Next.js开发服务器正在运行
- 确认API代理配置正确

4. **查看日志**:
- 检查浏览器控制台错误
- 检查网络请求是否正常
- 检查后端日志

## 需要帮助？

如果问题仍然存在，请提供：
1. 错误信息截图
2. 浏览器控制台日志
3. 后端服务日志
4. 数据库连接信息（脱敏）

这样我可以更好地帮助您解决问题。