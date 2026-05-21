-- P1-04: DB 角色分离（读写/迁移三账号）
-- 创建三个角色：读账号、写账号、迁移账号

-- 1. 创建迁移角色（用于执行 Flyway 迁移，拥有最高权限）
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'eris_migration') THEN
        CREATE ROLE eris_migration WITH LOGIN PASSWORD 'eris_migration_secret_2026' NOSUPERUSER CREATEROLE CREATEDB;
    END IF;
END
$$;

-- 2. 创建写角色（应用使用，可读写表且无结构变更权限）
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'eris_writer') THEN
        CREATE ROLE eris_writer WITH LOGIN PASSWORD 'eris_writer_secret_2026' NOSUPERUSER NOCREATEROLE NOCREATEDB;
    END IF;
END
$$;

-- 3. 创建读角色（只读，用于报表和监控）
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'eris_reader') THEN
        CREATE ROLE eris_reader WITH LOGIN PASSWORD 'eris_reader_secret_2026' NOSUPERUSER NOCREATEROLE NOCREATEDB;
    END IF;
END
$$;

-- 授予迁移角色所有权限
GRANT ALL PRIVILEGES ON DATABASE eris TO eris_migration;
GRANT ALL PRIVILEGES ON SCHEMA public TO eris_migration;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO eris_migration;

-- 授予写角色读写权限，不授予结构变更权限
GRANT CONNECT ON DATABASE eris TO eris_writer;
GRANT USAGE ON SCHEMA public TO eris_writer;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO eris_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO eris_writer;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO eris_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO eris_writer;

-- 授予读角色只读权限
GRANT CONNECT ON DATABASE eris TO eris_reader;
GRANT USAGE ON SCHEMA public TO eris_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO eris_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO eris_reader;

-- 确保现有表权限正确
DO $$
DECLARE
    table_record RECORD;
BEGIN
    FOR table_record IN 
        SELECT tablename FROM pg_tables WHERE schemaname = 'public'
    LOOP
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %I TO eris_writer', table_record.tablename);
        EXECUTE format('GRANT SELECT ON TABLE %I TO eris_reader', table_record.tablename);
        EXECUTE format('GRANT ALL ON TABLE %I TO eris_migration', table_record.tablename);
    END LOOP;
END
$$;

-- 确保现有序列权限正确
DO $$
DECLARE
    sequence_record RECORD;
BEGIN
    FOR sequence_record IN 
        SELECT sequencename FROM pg_sequences WHERE schemaname = 'public'
    LOOP
        EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %I TO eris_writer', sequence_record.sequencename);
        EXECUTE format('GRANT ALL ON SEQUENCE %I TO eris_migration', sequence_record.sequencename);
    END LOOP;
END
$$;
