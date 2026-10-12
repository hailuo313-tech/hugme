CREATE TABLE IF NOT EXISTS telegram_user_migration_campaigns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_account_id UUID NOT NULL REFERENCES telegram_accounts(id),
    target_account_id UUID NOT NULL REFERENCES telegram_accounts(id),
    name TEXT NOT NULL,
    intro_message TEXT NOT NULL,
    rate_per_minute INTEGER NOT NULL DEFAULT 5 CHECK (rate_per_minute BETWEEN 1 AND 30),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','running','paused','completed','cancelled')),
    filters JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by UUID NULL REFERENCES operators(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    CHECK (source_account_id <> target_account_id)
);

CREATE TABLE IF NOT EXISTS telegram_user_migration_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id UUID NOT NULL REFERENCES telegram_user_migration_campaigns(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),
    conversation_id UUID NULL REFERENCES conversations(id),
    telegram_chat_id BIGINT NOT NULL,
    source_account_id UUID NOT NULL REFERENCES telegram_accounts(id),
    target_account_id UUID NOT NULL REFERENCES telegram_accounts(id),
    source_access_hash BIGINT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending','resolving','resolved','sending','sent','success',
        'unreachable','restricted','retry_wait','failed','cancelled'
    )),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ NULL,
    sent_at TIMESTAMPTZ NULL,
    replied_at TIMESTAMPTZ NULL,
    video_sequence_reset_at TIMESTAMPTZ NULL,
    failure_code TEXT NULL,
    failure_reason TEXT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (campaign_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_tg_migration_campaign_status
    ON telegram_user_migration_campaigns(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_tg_migration_task_dispatch
    ON telegram_user_migration_tasks(status, next_attempt_at, created_at);
CREATE INDEX IF NOT EXISTS idx_tg_migration_task_target_chat
    ON telegram_user_migration_tasks(target_account_id, telegram_chat_id, sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_tg_migration_task_user
    ON telegram_user_migration_tasks(user_id, created_at DESC);

COMMENT ON TABLE telegram_user_migration_campaigns IS '被封 Telegram 接入账号的独立用户迁移批次';
COMMENT ON TABLE telegram_user_migration_tasks IS '逐用户解析、首条迁移消息、回复确认与视频序列切换状态';
