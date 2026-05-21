-- 创建默认管理员账号
-- 用户名: admin
-- 密码: admin123 (生产环境请及时修改)

INSERT INTO operators (username, password_hash, display_name, role, status)
VALUES (
    'admin',
    '0192023a7bbd73250516f069df18b500', -- SHA256 hash of 'admin123'
    '系统管理员',
    'admin',
    'active'
)
ON CONFLICT (username) DO NOTHING;