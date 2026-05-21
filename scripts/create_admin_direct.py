#!/usr/bin/env python3
"""
直接创建管理员账号的脚本
无需Docker，直接连接PostgreSQL数据库
"""

import hashlib
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    import asyncpg
    import asyncio
except ImportError:
    print("请先安装依赖: pip install asyncpg")
    sys.exit(1)


async def create_admin_operator():
    """创建管理员账号"""
    
    # 数据库连接配置
    DB_CONFIG = {
        'host': 'localhost',
        'port': 5432,
        'user': 'eris',
        'password': 'eris_secret_2026',  # 默认密码，根据实际情况修改
        'database': 'eris'
    }
    
    # 管理员账号信息
    ADMIN_USERNAME = 'admin'
    ADMIN_PASSWORD = 'admin123'
    ADMIN_DISPLAY_NAME = '系统管理员'
    ADMIN_ROLE = 'admin'
    
    # 生成密码哈希
    password_hash = hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest()
    print(f"密码哈希: {password_hash}")
    
    try:
        # 连接数据库
        conn = await asyncpg.connect(**DB_CONFIG)
        print("✅ 数据库连接成功")
        
        # 检查账号是否已存在
        existing = await conn.fetchval(
            "SELECT id FROM operators WHERE username = $1",
            ADMIN_USERNAME
        )
        
        if existing:
            print(f"⚠️  账号 '{ADMIN_USERNAME}' 已存在")
            choice = input("是否要重置密码? (y/n): ").strip().lower()
            if choice != 'y':
                print("操作取消")
                return
            
            # 更新密码
            await conn.execute(
                """UPDATE operators 
                   SET password_hash = $1, updated_at = NOW() 
                   WHERE username = $2""",
                password_hash, ADMIN_USERNAME
            )
            print(f"✅ 密码已重置")
        else:
            # 创建新账号
            await conn.execute(
                """INSERT INTO operators (username, password_hash, display_name, role, status)
                   VALUES ($1, $2, $3, $4, 'active')""",
                ADMIN_USERNAME, password_hash, ADMIN_DISPLAY_NAME, ADMIN_ROLE
            )
            print(f"✅ 管理员账号创建成功")
        
        # 验证创建结果
        admin_info = await conn.fetchrow(
            "SELECT username, display_name, role, status FROM operators WHERE username = $1",
            ADMIN_USERNAME
        )
        
        print("\n📋 账号信息:")
        print(f"  用户名: {admin_info['username']}")
        print(f"  显示名称: {admin_info['display_name']}")
        print(f"  角色: {admin_info['role']}")
        print(f"  状态: {admin_info['status']}")
        print(f"\n🔐 登录凭据:")
        print(f"  用户名: {ADMIN_USERNAME}")
        print(f"  密码: {ADMIN_PASSWORD}")
        
        await conn.close()
        
    except Exception as e:
        print(f"❌ 错误: {e}")
        print("\n请检查:")
        print("1. PostgreSQL服务是否启动")
        print("2. 数据库连接配置是否正确")
        print("3. 用户权限是否足够")
        sys.exit(1)


if __name__ == "__main__":
    print("=" * 50)
    print("ERIS 管理员账号创建工具")
    print("=" * 50)
    
    # 如果需要自定义数据库配置，可以修改下面的环境变量
    DB_HOST = os.environ.get('DB_HOST', 'localhost')
    DB_PORT = os.environ.get('DB_PORT', '5432')
    DB_USER = os.environ.get('DB_USER', 'eris')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', 'eris_secret_2026')
    DB_NAME = os.environ.get('DB_NAME', 'eris')
    
    print(f"\n数据库配置:")
    print(f"  主机: {DB_HOST}")
    print(f"  端口: {DB_PORT}")
    print(f"  用户: {DB_USER}")
    print(f"  数据库: {DB_NAME}")
    
    print("\n开始创建管理员账号...")
    asyncio.run(create_admin_operator())
    
    print("\n" + "=" * 50)
    print("完成！请使用上述凭据登录后台")
    print("=" * 50)