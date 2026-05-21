-- P2-09/P2-10: persist user level routing output for dashboard and payment recalculation.

ALTER TABLE user_profiles
    ADD COLUMN IF NOT EXISTS user_level VARCHAR(1) NOT NULL DEFAULT 'C'
        CHECK (user_level IN ('S', 'A', 'B', 'C', 'D')),
    ADD COLUMN IF NOT EXISTS chat_route VARCHAR(30) NOT NULL DEFAULT 'ai_auto'
        CHECK (chat_route IN ('manual_premium', 'ai_assisted', 'ai_auto')),
    ADD COLUMN IF NOT EXISTS country_code VARCHAR(2),
    ADD COLUMN IF NOT EXISTS level_updated_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS level_reason JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_user_profiles_level_route
    ON user_profiles(user_level, chat_route);

CREATE INDEX IF NOT EXISTS idx_user_profiles_country_code
    ON user_profiles(country_code);
