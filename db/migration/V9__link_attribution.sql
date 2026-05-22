-- Link tracking and App conversion attribution.
-- Connects script_hit_id -> link click -> app download/register -> payment.

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS attribution_tracking_id VARCHAR(64);

CREATE TABLE IF NOT EXISTS attribution_links (
    tracking_id        VARCHAR(64) PRIMARY KEY,
    destination_url    TEXT NOT NULL,
    user_id            UUID REFERENCES users(id) ON DELETE SET NULL,
    conversation_id    UUID REFERENCES conversations(id) ON DELETE SET NULL,
    message_id         UUID REFERENCES messages(id) ON DELETE SET NULL,
    script_hit_id      VARCHAR(128),
    script_template_id UUID,
    campaign_id        VARCHAR(80),
    platform           VARCHAR(40),
    persona_slug       VARCHAR(80),
    intent             VARCHAR(80),
    country_code       VARCHAR(2),
    age                INTEGER,
    user_level         VARCHAR(2),
    metadata           JSONB DEFAULT '{}'::jsonb,
    created_at         TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS attribution_events (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tracking_id        VARCHAR(64) REFERENCES attribution_links(tracking_id) ON DELETE SET NULL,
    event_type         VARCHAR(40) NOT NULL,
    user_id            UUID REFERENCES users(id) ON DELETE SET NULL,
    app_user_id        VARCHAR(120),
    order_id           UUID REFERENCES orders(id) ON DELETE SET NULL,
    amount_cents       INTEGER,
    currency           VARCHAR(5),
    country_code       VARCHAR(2),
    age                INTEGER,
    user_level         VARCHAR(2),
    device_os          VARCHAR(40),
    ip_address         INET,
    user_agent         TEXT,
    referrer           TEXT,
    metadata           JSONB DEFAULT '{}'::jsonb,
    created_at         TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_attribution_links_user_created
    ON attribution_links(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_attribution_links_script_hit
    ON attribution_links(script_hit_id);
CREATE INDEX IF NOT EXISTS idx_attribution_links_template
    ON attribution_links(script_template_id);
CREATE INDEX IF NOT EXISTS idx_attribution_links_country_age
    ON attribution_links(country_code, age);
CREATE INDEX IF NOT EXISTS idx_attribution_events_tracking_created
    ON attribution_events(tracking_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_attribution_events_type_created
    ON attribution_events(event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_attribution_events_user_created
    ON attribution_events(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_attribution_tracking
    ON orders(attribution_tracking_id);

COMMENT ON TABLE attribution_links IS 'Trackable links injected into script messages for attribution';
COMMENT ON TABLE attribution_events IS 'Click, download, register, and payment events attributed to tracking links';
