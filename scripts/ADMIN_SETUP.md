# 后台管理员账号设置指南

## 默认账号信息

- **用户名**: `admin`
- **密码**: `admin123`
- **角色**: 系统管理员

## 初始化步骤

### 方法1: 使用Docker执行SQL脚本

```bash
cd E:/eris
docker compose exec postgres psql -U eris -d eris -f /docker-entrypoint-initdb.d/create_admin_operator.sql
```

### 方法2: 手动执行SQL

```bash
cd E:/eris
docker compose exec postgres psql -U eris -d eris
```

然后在PostgreSQL命令行中执行：

```sql
INSERT INTO operators (username, password_hash, display_name, role, status)
VALUES (
    'admin',
    '0192023a7bbd73250516f069df18b500', -- SHA256 hash of 'admin123'
    '系统管理员',
    'admin',
    'active'
)
ON CONFLICT (username) DO NOTHING;
```

退出PostgreSQL: `\q`

### 方法3: 使用API创建（需要先有数据库访问权限）

如果您已经有数据库访问权限，也可以通过Python脚本创建：

```python
import hashlib

# 生成密码哈希
password = "admin123"
password_hash = hashlib.sha256(password.encode()).hexdigest()
print(f"Password hash: {password_hash}")
```

## 登录后台

1. 启动服务:
```bash
cd E:/eris
docker compose up -d
cd admin
npm run dev
```

2. 访问: `http://localhost:3000/admin`

3. 使用以下凭据登录:
   - 用户名: `admin`
   - 密码: `admin123`

## 安全建议

⚠️ **重要**: 首次登录后请立即修改默认密码！

### 修改密码

连接到数据库并执行：

```sql
-- 修改admin密码为 newpassword
-- 先生成新密码的SHA256哈希
-- 然后执行:
UPDATE operators 
SET password_hash = '新的SHA256哈希值' 
WHERE username = 'admin';
```

或者通过Python生成新密码哈希：

```python
import hashlib
new_password = "your_new_password"
new_hash = hashlib.sha256(new_password.encode()).hexdigest()
print(f"New password hash: {new_hash}")
```

## 创建其他管理员账号

```sql
INSERT INTO operators (username, password_hash, display_name, role, status)
VALUES (
    'operator1',
    '密码的SHA256哈希值',
    '操作员1',
    'operator',
    'active'
);
```

## 故障排查

### 登录失败

1. 检查数据库中是否有operator记录:
```sql
SELECT * FROM operators;
```

2. 检查账号状态是否为'active':
```sql
SELECT username, status FROM operators WHERE username = 'admin';
```

3. 检查密码哈希是否正确:
```python
import hashlib
test_password = "admin123"
test_hash = hashlib.sha256(test_password.encode()).hexdigest()
expected_hash = "0192023a7bbd73250516f069df18b500"
print(f"Match: {test_hash == expected_hash}")
```