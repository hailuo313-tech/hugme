-- ERIS 数据库初始化脚本
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- 用户表
CREATE TABLE IF NOT EXISTS users (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    channel             VARCHAR(20) NOT NULL,
    external_id         VARCHAR(100) NOT NULL,
    nickname            VARCHAR(100),
    language            VARCHAR(10) DEFAULT 'en',
    timezone            VARCHAR(50) DEFAULT 'UTC',
    status              VARCHAR(20) DEFAULT 'active',
    age_verified        BOOLEAN DEFAULT FALSE,
    is_minor_suspected  BOOLEAN DEFAULT FALSE,
    risk_level          VARCHAR(20) DEFAULT 'normal',
    opt_out_marketing   BOOLEAN DEFAULT FALSE,
    notification_opt_in BOOLEAN DEFAULT TRUE,
    gdpr_consent_at     TIMESTAMP,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW(),
    UNIQUE(channel, external_id)
);

-- 用户画像表
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id                 UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    current_character_id    UUID,
    preferences             JSONB DEFAULT '{}',
    interests               JSONB DEFAULT '[]',
    emotional_patterns      JSONB DEFAULT '{}',
    chat_style              VARCHAR(30),
    forbidden_topics        JSONB DEFAULT '[]',
    relationship_stage      VARCHAR(10) DEFAULT 'S0',
    risk_score              INTEGER DEFAULT 0,
    vip_level               INTEGER DEFAULT 0,
    initiation_score        FLOAT DEFAULT 0,
    emotion_score           FLOAT DEFAULT 0,
    retention_score         FLOAT DEFAULT 0,
    dependency_score        FLOAT DEFAULT 0,
    loneliness_score        FLOAT DEFAULT 35,
    score_stage             VARCHAR(20) DEFAULT 'cold_start',
    trigger_threshold       FLOAT DEFAULT 65,
    score_updated_at        TIMESTAMP,
    notes                   TEXT,
    updated_at              TIMESTAMP DEFAULT NOW()
);

-- 角色表
CREATE TABLE IF NOT EXISTS characters (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                    VARCHAR(100) NOT NULL,
    age_feel                VARCHAR(50),
    region                  VARCHAR(50),
    occupation              VARCHAR(100),
    background              TEXT,
    relationship_position   VARCHAR(100),
    profile_details         JSONB DEFAULT '{}'::jsonb,
    default_language        VARCHAR(10) DEFAULT 'en',
    supported_languages     JSONB DEFAULT '["en"]',
    gentle_score            INTEGER DEFAULT 50,
    proactive_score         INTEGER DEFAULT 50,
    flirt_score             INTEGER DEFAULT 30,
    humor_score             INTEGER DEFAULT 40,
    emotional_depth_score   INTEGER DEFAULT 60,
    boundary_score          INTEGER DEFAULT 70,
    reply_length            VARCHAR(10) DEFAULT 'medium',
    tone                    VARCHAR(20) DEFAULT 'warm',
    emoji_frequency         VARCHAR(10) DEFAULT 'low',
    prompt_en               TEXT,
    prompt_es               TEXT,
    prompt_fr               TEXT,
    prompt_de               TEXT,
    status                  VARCHAR(20) DEFAULT 'draft',
    created_at              TIMESTAMP DEFAULT NOW(),
    updated_at              TIMESTAMP DEFAULT NOW()
);

-- 会话表
CREATE TABLE IF NOT EXISTS conversations (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id                 UUID REFERENCES users(id) ON DELETE CASCADE,
    character_id            UUID REFERENCES characters(id),
    channel                 VARCHAR(20),
    state                   VARCHAR(30) DEFAULT 'AI_ACTIVE',
    assigned_operator_id    UUID,
    handoff_count           INTEGER DEFAULT 0,
    ai_model_used           VARCHAR(50),
    last_message_at         TIMESTAMP,
    created_at              TIMESTAMP DEFAULT NOW(),
    updated_at              TIMESTAMP DEFAULT NOW()
);

-- 消息表
CREATE TABLE IF NOT EXISTS messages (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id     UUID REFERENCES conversations(id) ON DELETE CASCADE,
    sender_type         VARCHAR(20),
    sender_id           VARCHAR(100),
    content             TEXT,
    content_type        VARCHAR(20) DEFAULT 'text',
    safety_result       JSONB,
    consistency_score   FLOAT,
    used_script_id      UUID,
    is_operator_message BOOLEAN DEFAULT FALSE,
    model_name          VARCHAR(50),
    created_at          TIMESTAMP DEFAULT NOW()
);

-- 记忆表（含 pgvector 向量字段）
CREATE TABLE IF NOT EXISTS memories (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID REFERENCES users(id) ON DELETE CASCADE,
    character_id        UUID,
    memory_scope        VARCHAR(20) DEFAULT 'global',
    memory_type         VARCHAR(30),
    content             TEXT NOT NULL,
    summary             TEXT,
    importance_score    FLOAT DEFAULT 5,
    confidence_score    FLOAT DEFAULT 1.0,
    emotion_tags        JSONB DEFAULT '[]',
    source_message_id   UUID,
    is_active           BOOLEAN DEFAULT TRUE,
    last_used_at        TIMESTAMP,
    correction_count    INTEGER DEFAULT 0,
    operator_modified   BOOLEAN DEFAULT FALSE,
    embedding           vector(1536),
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);

-- D8-1：memories B-tree / 部分索引（loneliness 时间窗、retrieve fallback 排序；见 docs/D8_PERFORMANCE_INDEXES.md）
CREATE INDEX IF NOT EXISTS idx_memories_user_active_created_at
    ON memories (user_id, created_at DESC)
    WHERE is_active = true;

CREATE INDEX IF NOT EXISTS idx_memories_user_active_importance_created
    ON memories (user_id, importance_score DESC, created_at DESC)
    WHERE is_active = true;

-- 接管任务表
CREATE TABLE IF NOT EXISTS handoff_tasks (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id                 UUID REFERENCES users(id),
    conversation_id         UUID REFERENCES conversations(id),
    priority                VARCHAR(5) DEFAULT 'P3',
    trigger_reason          VARCHAR(100),
    status                  VARCHAR(30) DEFAULT 'pending',
    assigned_operator_id    UUID,
    locked_at               TIMESTAMP,
    closed_at               TIMESTAMP,
    created_at              TIMESTAMP DEFAULT NOW()
);

-- 通知任务表
CREATE TABLE IF NOT EXISTS notification_tasks (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID REFERENCES users(id),
    channel             VARCHAR(20),
    notification_type   VARCHAR(50),
    template_id         UUID,
    payload             JSONB,
    scheduled_at        TIMESTAMP,
    sent_at             TIMESTAMP,
    status              VARCHAR(20) DEFAULT 'pending',
    failure_reason      TEXT,
    created_at          TIMESTAMP DEFAULT NOW()
);

-- 订单表
CREATE TABLE IF NOT EXISTS orders (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID REFERENCES users(id),
    product_id          VARCHAR(100),
    amount              INTEGER NOT NULL,
    currency            VARCHAR(5) DEFAULT 'USD',
    status              VARCHAR(20) DEFAULT 'pending',
    payment_provider    VARCHAR(20) DEFAULT 'stripe',
    provider_order_id   VARCHAR(200),
    refund_status       VARCHAR(20),
    refunded_at         TIMESTAMP,
    created_at          TIMESTAMP DEFAULT NOW(),
    paid_at             TIMESTAMP
);

-- 风险事件表
CREATE TABLE IF NOT EXISTS risk_events (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID REFERENCES users(id),
    risk_type           VARCHAR(50),
    severity            VARCHAR(10),
    trigger_message_id  UUID,
    description         TEXT,
    handled_by          UUID,
    handled_at          TIMESTAMP,
    resolution          TEXT,
    created_at          TIMESTAMP DEFAULT NOW()
);

-- 话术库表
CREATE TABLE IF NOT EXISTS scripts (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    character_id            UUID,
    language                VARCHAR(10) DEFAULT 'en',
    relationship_stage      VARCHAR(10),
    emotion_state           VARCHAR(30),
    loneliness_score_min    FLOAT DEFAULT 0,
    loneliness_score_max    FLOAT DEFAULT 100,
    script_type             VARCHAR(30),
    content                 TEXT NOT NULL,
    risk_level              VARCHAR(10) DEFAULT 'low',
    conversion_goal         VARCHAR(50),
    review_status           VARCHAR(20) DEFAULT 'draft',
    forbidden_scenarios     JSONB DEFAULT '[]',
    created_at              TIMESTAMP DEFAULT NOW(),
    updated_at              TIMESTAMP DEFAULT NOW()
);

-- 运营后台账号表 (D5-1)
CREATE TABLE IF NOT EXISTS operators (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username        VARCHAR(50) NOT NULL UNIQUE,
    password_hash   VARCHAR(64) NOT NULL,
    display_name    VARCHAR(100),
    role            VARCHAR(20) DEFAULT 'operator',
    status          VARCHAR(20) DEFAULT 'active',
    last_login_at   TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- Stripe Webhook 幂等表 (D6-2)
-- 同一 Stripe event.id 多次到达只处理一次；列名/约束与 payments.stripe_webhook
-- 内逻辑对齐：先 INSERT 抢占（ON CONFLICT DO NOTHING），再处理业务，最后回填 result/handled_at。
CREATE TABLE IF NOT EXISTS stripe_webhook_events (
    event_id        VARCHAR(64) PRIMARY KEY,        -- Stripe event.id (evt_*)
    event_type      VARCHAR(80) NOT NULL,           -- e.g. checkout.session.completed
    payload         JSONB NOT NULL,                 -- 原始 event 体（剥离 signing key 后保存以便回放）
    result          VARCHAR(20) DEFAULT 'received', -- received | processed | ignored | failed
    error           TEXT,
    received_at     TIMESTAMP DEFAULT NOW(),
    handled_at      TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_stripe_webhook_events_type_received
    ON stripe_webhook_events(event_type, received_at DESC);

-- P2: Operator quality review scores
CREATE TABLE IF NOT EXISTS operator_quality_scores (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    handoff_task_id UUID REFERENCES handoff_tasks(id) ON DELETE SET NULL,
    operator_id UUID REFERENCES operators(id) ON DELETE SET NULL,
    reviewer_operator_id UUID REFERENCES operators(id) ON DELETE SET NULL,
    conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
    overall_score INTEGER NOT NULL CHECK (overall_score BETWEEN 0 AND 100),
    empathy_score INTEGER CHECK (empathy_score BETWEEN 0 AND 100),
    accuracy_score INTEGER CHECK (accuracy_score BETWEEN 0 AND 100),
    safety_score INTEGER CHECK (safety_score BETWEEN 0 AND 100),
    timeliness_score INTEGER CHECK (timeliness_score BETWEEN 0 AND 100),
    result VARCHAR(30) NOT NULL DEFAULT 'needs_review',
    issue_tags JSONB NOT NULL DEFAULT '[]',
    review_notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_operator_quality_scores_operator_created
    ON operator_quality_scores(operator_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_operator_quality_scores_handoff
    ON operator_quality_scores(handoff_task_id);
CREATE INDEX IF NOT EXISTS idx_operator_quality_scores_conversation
    ON operator_quality_scores(conversation_id);
CREATE INDEX IF NOT EXISTS idx_operator_quality_scores_result
    ON operator_quality_scores(result);

-- P3: A/B experiments
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
