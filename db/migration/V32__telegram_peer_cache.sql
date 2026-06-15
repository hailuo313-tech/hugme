-- Cache which MTProto account can reach a Telegram peer (account_id + chat_id).

CREATE TABLE IF NOT EXISTS telegram_peer_cache (
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
    account_id UUID NOT NULL REFERENCES telegram_accounts(id) ON DELETE CASCADE,
    chat_id BIGINT NOT NULL,
    access_hash BIGINT,
    source VARCHAR(64) NOT NULL DEFAULT 'unknown',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (account_id, chat_id)
);

CREATE INDEX IF NOT EXISTS idx_telegram_peer_cache_conversation
    ON telegram_peer_cache(conversation_id, last_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_telegram_peer_cache_user
    ON telegram_peer_cache(user_id, last_seen_at DESC);
