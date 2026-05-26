-- P1-01 / P1-16: premium chat trace tables and general audit log.

CREATE TABLE IF NOT EXISTS premium_chat_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
    message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
    external_user_id VARCHAR(128),
    platform VARCHAR(40) NOT NULL DEFAULT 'telegram_real_user',
    account_id VARCHAR(64),
    sender_phone VARCHAR(32),
    direction VARCHAR(20) NOT NULL,
    message_type VARCHAR(20) NOT NULL DEFAULT 'text',
    script_hit_id VARCHAR(128),
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_premium_chat_logs_user_created
    ON premium_chat_logs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_premium_chat_logs_external_user_created
    ON premium_chat_logs(external_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_premium_chat_logs_conversation_created
    ON premium_chat_logs(conversation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_premium_chat_logs_script_hit
    ON premium_chat_logs(script_hit_id);

CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trace_id VARCHAR(64),
    event_type VARCHAR(80) NOT NULL,
    source VARCHAR(80) NOT NULL,
    actor_type VARCHAR(40),
    actor_id VARCHAR(128),
    user_id VARCHAR(128),
    conversation_id UUID,
    message_id UUID,
    platform VARCHAR(40),
    account_id VARCHAR(64),
    sender_phone VARCHAR(32),
    script_hit_id VARCHAR(128),
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at
    ON audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_created
    ON audit_logs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_trace_id
    ON audit_logs(trace_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_event_created
    ON audit_logs(event_type, created_at DESC);

COMMENT ON TABLE premium_chat_logs IS 'P1-01 premium chat message trace table for S/A paid chat analysis';
COMMENT ON TABLE audit_logs IS 'P1-16 append-only audit log, queryable by recent 100 records';
COMMENT ON COLUMN audit_logs.user_id IS 'External or canonical user id; kept VARCHAR because inbound_queue emits external_user_id before DB binding';
COMMENT ON COLUMN audit_logs.sender_phone IS 'Stored only when required for audit; API responses must redact this field';
