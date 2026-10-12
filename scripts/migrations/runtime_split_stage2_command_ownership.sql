-- Stage 2: reliable command queue and Telegram account ownership.
-- Additive only: new empty tables and indexes. Existing table semantics unchanged.
-- Consumers stay closed in this stage; do not apply on production until review.

CREATE TABLE IF NOT EXISTS runtime_instances (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    instance_key VARCHAR(128) NOT NULL UNIQUE,
    process_role VARCHAR(32) NOT NULL DEFAULT 'all'
        CHECK (process_role IN ('all', 'api', 'telegram_runtime')),
    status VARCHAR(20) NOT NULL DEFAULT 'starting'
        CHECK (status IN ('starting', 'ready', 'draining', 'stopped')),
    hostname VARCHAR(128),
    pid INTEGER,
    version VARCHAR(64),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS runtime_commands (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    command_type VARCHAR(64) NOT NULL,
    account_id UUID NULL REFERENCES telegram_accounts(id) ON DELETE SET NULL,
    conversation_id UUID NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'leased', 'succeeded', 'failed', 'cancelled', 'expired')),
    priority INTEGER NOT NULL DEFAULT 0,
    generation BIGINT NOT NULL DEFAULT 0,
    idempotency_key VARCHAR(128) NOT NULL,
    lease_owner VARCHAR(128),
    lease_until TIMESTAMPTZ,
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    result JSONB,
    error TEXT,
    created_by VARCHAR(128),
    trace_id VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS runtime_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    command_id UUID NULL REFERENCES runtime_commands(id) ON DELETE SET NULL,
    account_id UUID NULL REFERENCES telegram_accounts(id) ON DELETE SET NULL,
    event_type VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    generation BIGINT,
    instance_key VARCHAR(128),
    trace_id VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS telegram_account_ownership (
    account_id UUID PRIMARY KEY REFERENCES telegram_accounts(id) ON DELETE CASCADE,
    owner VARCHAR(20) NOT NULL DEFAULT 'legacy'
        CHECK (owner IN ('legacy', 'runtime')),
    generation BIGINT NOT NULL DEFAULT 1,
    owner_instance_id UUID NULL REFERENCES runtime_instances(id) ON DELETE SET NULL,
    lease_until TIMESTAMPTZ,
    switch_status VARCHAR(20) NOT NULL DEFAULT 'stable'
        CHECK (switch_status IN ('stable', 'draining', 'switching')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_runtime_instances_heartbeat
    ON runtime_instances (last_heartbeat_at DESC);

CREATE INDEX IF NOT EXISTS idx_runtime_instances_role_status
    ON runtime_instances (process_role, status);

CREATE INDEX IF NOT EXISTS idx_runtime_commands_claim
    ON runtime_commands (priority DESC, available_at, created_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_runtime_commands_lease_reclaim
    ON runtime_commands (lease_until)
    WHERE status = 'leased';

CREATE INDEX IF NOT EXISTS idx_runtime_commands_generation
    ON runtime_commands (account_id, generation);

CREATE INDEX IF NOT EXISTS idx_runtime_commands_account_created
    ON runtime_commands (account_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_runtime_commands_idempotency
    ON runtime_commands (idempotency_key);

CREATE INDEX IF NOT EXISTS idx_runtime_events_command
    ON runtime_events (command_id, created_at);

CREATE INDEX IF NOT EXISTS idx_runtime_events_account_created
    ON runtime_events (account_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_runtime_events_type_created
    ON runtime_events (event_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_telegram_account_ownership_owner_generation
    ON telegram_account_ownership (owner, generation);

CREATE INDEX IF NOT EXISTS idx_telegram_account_ownership_instance
    ON telegram_account_ownership (owner_instance_id);

COMMENT ON TABLE runtime_instances IS 'Stage 2: Telegram/API runtime process registry and heartbeat';
COMMENT ON TABLE runtime_commands IS 'Stage 2: durable command queue with lease, priority, generation fencing and idempotency';
COMMENT ON TABLE runtime_events IS 'Stage 2: runtime-to-API event log; consumers remain disabled';
COMMENT ON TABLE telegram_account_ownership IS 'Stage 2: per-account owner and generation; empty means treat as legacy';
COMMENT ON COLUMN runtime_commands.generation IS 'Fencing token copied from account ownership at enqueue';
COMMENT ON COLUMN runtime_commands.idempotency_key IS 'Caller-supplied unique key to prevent duplicate sends';
COMMENT ON COLUMN telegram_account_ownership.generation IS 'Increments on owner switch; stale commands must be rejected';
