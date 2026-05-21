# ERIS 服务启动完整指南

## 🚨 问题确认

当前服务状态：
- ✅ 前端服务 (端口3000) - 运行中
- ❌ 后端API (端口8000) - 未运行
- ❌ 数据库 (端口5432) - 未运行

**这就是无法登录的根本原因**

## 🔧 解决方案选择

### 方案1: 安装并使用Docker（推荐）

这是最简单的方式，所有服务都在Docker容器中运行。

#### 1.1 安装Docker Desktop

1. 下载Docker Desktop for Windows:
   https://www.docker.com/products/docker-desktop/

2. 运行安装程序，按默认设置安装

3. 安装完成后启动Docker Desktop

4. 等待Docker Desktop完全启动（系统托盘图标显示正常）

#### 1.2 启动所有服务

```bash
cd E:\eris
docker compose up -d
```

#### 1.3 创建管理员账号

```bash
docker compose exec postgres psql -U eris -d eris -c "
INSERT INTO operators (username, password_hash, display_name, role, status)
VALUES (
    'admin',
    '0192023a7bbd73250516f069df18b500',
    '系统管理员',
    'admin',
    'active'
) ON CONFLICT (username) DO NOTHING;
"
```

#### 1.4 访问后台

- 前端: http://localhost:3000/admin
- 用户名: admin
- 密码: admin123

---

### 方案2: 使用本地PostgreSQL

如果您本地已经安装了PostgreSQL。

#### 2.1 确认PostgreSQL服务

```bash
# 检查PostgreSQL服务状态
sc query postgresql-x64-14

# 或者其他版本号
sc query | findstr -i postgres
```

#### 2.2 启动PostgreSQL服务

```bash
# 启动服务
net start postgresql-x64-14

# 或使用服务管理器
services.msc
```

#### 2.3 创建数据库

```bash
# 使用psql连接
psql -U postgres

# 创建数据库和用户
CREATE DATABASE eris;
CREATE USER eris WITH PASSWORD 'eris_secret_2026';
GRANT ALL PRIVILEGES ON DATABASE eris TO eris;
```

#### 2.4 运行数据库迁移

```bash
cd E:\eris
psql -U eris -d eris -f scripts/init.sql
```

#### 2.5 创建管理员账号

```bash
psql -U eris -d eris -c "
INSERT INTO operators (username, password_hash, display_name, role, status)
VALUES (
    'admin',
    '0192023a7bbd73250516f069df18b500',
    '系统管理员',
    'admin',
    'active'
);
"
```

#### 2.6 启动后端服务

```bash
cd E:\eris\app
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

### 方案3: 使用云数据库

如果本地安装数据库困难，可以使用云PostgreSQL服务。

#### 3.1 注册云数据库服务
- Supabase (免费): https://supabase.com/
- Neon (免费): https://neon.tech/
- Railway (免费额度): https://railway.app/

#### 3.2 获取连接信息
- 数据库主机
- 端口
- 用户名
- 密码
- 数据库名

#### 3.3 更新配置

创建 `.env` 文件：
```env
DATABASE_URL=postgresql+asyncpg://user:password@host:port/dbname
POSTGRES_DB=eris
POSTGRES_USER=your_user
POSTGRES_PASSWORD=your_password
```

#### 3.4 运行迁移和启动服务

同方案2的步骤2.4-2.6

---

## 🚀 快速启动检查清单

使用Docker方式（推荐）：

- [ ] Docker Desktop已安装
- [ ] Docker Desktop正在运行
- [ ] 执行 `docker compose up -d`
- [ ] 执行数据库初始化脚本
- [ ] 创建管理员账号
- [ ] 访问 http://localhost:3000/admin
- [ ] 使用 admin/admin123 登录

---

## 🐛 故障排查

### Docker相关问题

**Docker命令不可用：**
1. 重启命令提示符
2. 检查Docker Desktop是否运行
3. 检查环境变量PATH

**容器启动失败：**
```bash
# 查看日志
docker compose logs

# 查看特定服务日志
docker compose logs api
docker compose logs postgres
```

### PostgreSQL相关问题

**连接失败：**
1. 确认服务正在运行
2. 检查防火墙设置
3. 验证连接参数

**权限问题：**
```sql
-- 授予必要权限
GRANT ALL PRIVILEGES ON DATABASE eris TO eris;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO eris;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO eris;
```

### 后端API问题

**端口冲突：**
```bash
# 检查端口占用
netstat -ano | findstr :8000

# 更改端口
python -m uvicorn main:app --host 0.0.0.0 --port 8001
```

**依赖缺失：**
```bash
pip install -r requirements.txt
```

---

## 📞 需要帮助？

如果以上方案都无法解决，请告诉我：

1. 您的Windows版本
2. 是否已安装Docker Desktop
3. 是否已安装PostgreSQL
4. 具体的错误信息

我会根据您的具体情况提供更精准的解决方案。