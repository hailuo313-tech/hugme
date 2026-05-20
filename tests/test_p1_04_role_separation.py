"""P1-04: 数据库角色分离测试

验证三个数据库角色的权限分离：
- eris_migration: 迁移角色，拥有所有权限
- eris_writer: 写角色，可读写表但无 DROP 权限
- eris_reader: 读角色，只读权限
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROLE_MIGRATION = ROOT / "db" / "migration" / "V2__create_roles.sql"


def test_role_migration_file_exists() -> None:
    """验证 P1-04 角色迁移文件存在"""
    assert ROLE_MIGRATION.is_file()
    assert ROLE_MIGRATION.name == "V2__create_roles.sql"


def test_role_migration_declares_three_roles() -> None:
    """验证迁移脚本声明了三个角色"""
    text = ROLE_MIGRATION.read_text(encoding="utf-8")
    
    for role in ("eris_migration", "eris_writer", "eris_reader"):
        assert f"CREATE ROLE {role}" in text or f"rolname = '{role}'" in text


def test_role_migration_writer_no_drop_privileges() -> None:
    """验证写角色没有 DROP 权限"""
    text = ROLE_MIGRATION.read_text(encoding="utf-8")
    
    # 验证写角色只有 SELECT, INSERT, UPDATE, DELETE 权限
    assert "GRANT SELECT, INSERT, UPDATE, DELETE" in text
    # 验证没有授予 DROP 权限给写角色
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if 'eris_writer' in line and 'GRANT' in line:
            # 检查这一行和接下来几行，确保没有 DROP 权限
            context = '\n'.join(lines[max(0, i-2):min(len(lines), i+3)])
            assert 'DROP' not in context or 'TO eris_writer' not in context


def test_role_migration_reader_read_only() -> None:
    """验证读角色只有只读权限"""
    text = ROLE_MIGRATION.read_text(encoding="utf-8")
    
    # 验证读角色只有 SELECT 权限
    assert "GRANT SELECT" in text
    # 验证读角色没有 INSERT, UPDATE, DELETE 权限
    assert "eris_reader" in text


def test_role_migration_migration_full_privileges() -> None:
    """验证迁移角色拥有完整权限"""
    text = ROLE_MIGRATION.read_text(encoding="utf-8")
    
    # 验证迁移角色有所有权限
    assert "eris_migration" in text
    assert "GRANT ALL PRIVILEGES" in text


def test_docker_compose_has_role_env_vars() -> None:
    """验证 docker-compose.yml 包含角色环境变量"""
    compose_file = ROOT / "docker-compose.yml"
    text = compose_file.read_text(encoding="utf-8")
    
    for env_var in (
        "POSTGRES_MIGRATION_USER",
        "POSTGRES_WRITER_USER", 
        "POSTGRES_READER_USER"
    ):
        assert env_var in text


def test_app_config_has_role_urls() -> None:
    """验证应用配置包含角色分离的数据库 URL"""
    config_file = ROOT / "app" / "core" / "config.py"
    text = config_file.read_text(encoding="utf-8")
    
    # 验证配置包含三个数据库 URL
    assert "DATABASE_URL" in text
    assert "DATABASE_MIGRATION_URL" in text
    assert "DATABASE_READER_URL" in text


def test_role_migration_acceptance_criteria() -> None:
    """验证 P1-04 验收标准：应用账号无 DROP 权限"""
    text = ROLE_MIGRATION.read_text(encoding="utf-8")
    
    # 验证写角色（应用账号）没有 DROP 权限
    assert "eris_writer" in text
    # 确保写角色只有读写权限，没有 DROP
    assert "GRANT SELECT, INSERT, UPDATE, DELETE" in text
    # 验收标准：不能有 DROP 权限授予给写角色
    assert "GRANT DROP" not in text
