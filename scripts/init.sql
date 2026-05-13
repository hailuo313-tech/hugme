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
    cre
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
