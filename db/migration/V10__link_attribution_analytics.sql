-- Complete link attribution analytics dimensions and app user binding.

ALTER TABLE attribution_links
    ADD COLUMN IF NOT EXISTS sender_account_id VARCHAR(120),
    ADD COLUMN IF NOT EXISTS sent_at TIMESTAMP DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS scene_step VARCHAR(80),
    ADD COLUMN IF NOT EXISTS script_category VARCHAR(80),
    ADD COLUMN IF NOT EXISTS is_t1_country BOOLEAN;

CREATE TABLE IF NOT EXISTS app_user_attribution_bindings (
    app_user_id        VARCHAR(120) PRIMARY KEY,
    telegram_user_id   UUID REFERENCES users(id) ON DELETE SET NULL,
    tracking_id        VARCHAR(64) REFERENCES attribution_links(tracking_id) ON DELETE SET NULL,
    first_seen_at      TIMESTAMP DEFAULT NOW(),
    registered_at      TIMESTAMP,
    metadata           JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_attribution_links_sender_sent
    ON attribution_links(sender_account_id, sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_attribution_links_persona_intent
    ON attribution_links(persona_slug, intent);
CREATE INDEX IF NOT EXISTS idx_attribution_links_scene_category
    ON attribution_links(scene_step, script_category);
CREATE INDEX IF NOT EXISTS idx_attribution_links_t1_sent
    ON attribution_links(is_t1_country, sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_attribution_events_app_user_created
    ON attribution_events(app_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_app_user_attribution_tracking
    ON app_user_attribution_bindings(tracking_id);

COMMENT ON COLUMN attribution_links.sender_account_id IS 'Telegram or outbound account that sent the tracked script link';
COMMENT ON COLUMN attribution_links.sent_at IS 'Time the script link was sent or exposed to the user';
COMMENT ON COLUMN attribution_links.scene_step IS 'Business scene or funnel step for the script';
COMMENT ON COLUMN attribution_links.script_category IS 'Script template category used for rollups';
COMMENT ON COLUMN attribution_links.is_t1_country IS 'Snapshot of whether the user country was T1 when the link was created';
COMMENT ON TABLE app_user_attribution_bindings IS 'Telegram user to App user attribution binding by tracking link';
