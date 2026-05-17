-- P3: A/B experiments core tables

CREATE TABLE IF NOT EXISTS ab_experiments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    experiment_key VARCHAR(80) NOT NULL UNIQUE,
    name VARCHAR(160) NOT NULL,
    description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'running', 'paused', 'archived')),
    owner_operator_id UUID REFERENCES operators(id) ON DELETE SET NULL,
    target_rules JSONB NOT NULL DEFAULT '{}',
    start_at TIMESTAMP,
    end_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ab_variants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    experiment_id UUID NOT NULL REFERENCES ab_experiments(id) ON DELETE CASCADE,
    variant_key VARCHAR(80) NOT NULL,
    name VARCHAR(160) NOT NULL,
    weight INTEGER NOT NULL DEFAULT 0 CHECK (weight >= 0 AND weight <= 10000),
    config JSONB NOT NULL DEFAULT '{}',
    is_control BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (experiment_id, variant_key)
);

CREATE TABLE IF NOT EXISTS ab_assignments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    experiment_id UUID NOT NULL REFERENCES ab_experiments(id) ON DELETE CASCADE,
    variant_id UUID NOT NULL REFERENCES ab_variants(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    assignment_key VARCHAR(160),
    context JSONB NOT NULL DEFAULT '{}',
    assigned_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (experiment_id, user_id),
    UNIQUE (experiment_id, assignment_key)
);

CREATE TABLE IF NOT EXISTS ab_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    experiment_id UUID NOT NULL REFERENCES ab_experiments(id) ON DELETE CASCADE,
    variant_id UUID REFERENCES ab_variants(id) ON DELETE SET NULL,
    assignment_id UUID REFERENCES ab_assignments(id) ON DELETE SET NULL,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    event_type VARCHAR(80) NOT NULL,
    event_value FLOAT,
    metadata JSONB NOT NULL DEFAULT '{}',
    occurred_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ab_experiments_status
    ON ab_experiments(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_ab_variants_experiment
    ON ab_variants(experiment_id);
CREATE INDEX IF NOT EXISTS idx_ab_assignments_experiment_user
    ON ab_assignments(experiment_id, user_id);
CREATE INDEX IF NOT EXISTS idx_ab_assignments_experiment_key
    ON ab_assignments(experiment_id, assignment_key);
CREATE INDEX IF NOT EXISTS idx_ab_events_experiment_type_created
    ON ab_events(experiment_id, event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ab_events_user_created
    ON ab_events(user_id, created_at DESC);
