-- Video call broadcast: Telethon + PyTgCalls stream jobs (default disabled via CALL_BROADCAST_ENABLED)

CREATE TABLE IF NOT EXISTS video_broadcast_assets (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title               TEXT NOT NULL,
    file_path           TEXT NOT NULL,
    duration_seconds    INTEGER,
    ffmpeg_profile      JSONB NOT NULL DEFAULT '{}',
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'archived')),
    metadata            JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_video_broadcast_assets_status
    ON video_broadcast_assets(status);

CREATE TABLE IF NOT EXISTS call_broadcast_jobs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             TEXT NOT NULL,
    external_user_id    TEXT,
    conversation_id     TEXT,
    chat_id             BIGINT NOT NULL,
    account_id          UUID REFERENCES telegram_accounts(id),
    video_asset_id      UUID REFERENCES video_broadcast_assets(id),
    trigger_source      TEXT NOT NULL DEFAULT 'inbound_keyword',
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN (
                            'pending', 'dialing', 'streaming',
                            'completed', 'failed', 'cancelled'
                        )),
    send_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at          TIMESTAMPTZ,
    ended_at            TIMESTAMPTZ,
    failure_reason      TEXT,
    retry_count         INTEGER NOT NULL DEFAULT 0,
    max_retries         INTEGER NOT NULL DEFAULT 2,
    priority            INTEGER NOT NULL DEFAULT 50,
    rule_key            TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}',
    trace_id            TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_call_broadcast_jobs_status_send_at
    ON call_broadcast_jobs(status, send_at);

CREATE INDEX IF NOT EXISTS idx_call_broadcast_jobs_user_rule
    ON call_broadcast_jobs(user_id, rule_key)
    WHERE rule_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_call_broadcast_jobs_account_status
    ON call_broadcast_jobs(account_id, status);
