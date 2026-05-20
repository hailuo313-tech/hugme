-- P1-09: Telegram accounts table for multi-account StringSession management
-- 支持多个 Telegram 账号的 StringSession 存储和状态管理

CREATE TABLE IF NOT EXISTS telegram_accounts (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    phone               VARCHAR(20) NOT NULL UNIQUE,
    session_string      TEXT NOT NULL,  -- 加密的 StringSession
    status              VARCHAR(20) DEFAULT 'disconnected',
                        CHECK (status IN ('disconnected', 'connecting', 'connected', 'error', 'banned')),
    is_active           BOOLEAN DEFAULT TRUE,
    is_bot              BOOLEAN DEFAULT FALSE,
    display_name        VARCHAR(100),
    username            VARCHAR(50),
    user_id             BIGINT,  -- Telegram user_id
    last_connected_at   TIMESTAMP,
    last_error_at       TIMESTAMP,
    error_message       TEXT,
    metadata            JSONB DEFAULT '{}',
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);

-- 索引：按状态查询活跃账号
CREATE INDEX IF NOT EXISTS idx_telegram_accounts_status_active
    ON telegram_accounts(status, is_active)
    WHERE is_active = TRUE;

-- 索引：按手机号查询
CREATE INDEX IF NOT EXISTS idx_telegram_accounts_phone
    ON telegram_accounts(phone);

-- 索引：按最后连接时间排序
CREATE INDEX IF NOT EXISTS idx_telegram_accounts_last_connected
    ON telegram_accounts(last_connected_at DESC)
    WHERE is_active = TRUE;

-- 触发器：自动更新 updated_at
CREATE OR REPLACE FUNCTION update_telegram_accounts_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_telegram_accounts_updated_at
    BEFORE UPDATE ON telegram_accounts
    FOR EACH ROW
    EXECUTE FUNCTION update_telegram_accounts_updated_at();

-- 注释
COMMENT ON TABLE telegram_accounts IS 'P1-09: Telegram 账号表，存储多账号 StringSession 和状态';
COMMENT ON COLUMN telegram_accounts.session_string IS '加密的 Telethon StringSession';
COMMENT ON COLUMN telegram_accounts.status IS '连接状态: disconnected, connecting, connected, error, banned';
COMMENT ON COLUMN telegram_accounts.is_active IS '是否启用该账号用于发送消息';
COMMENT ON COLUMN telegram_accounts.is_bot IS '是否为 Bot 账号';
COMMENT ON COLUMN telegram_accounts.user_id IS 'Telegram 系统分配的 user_id';
COMMENT ON COLUMN telegram_accounts.metadata IS '额外元数据，如设备信息、IP 限制等';