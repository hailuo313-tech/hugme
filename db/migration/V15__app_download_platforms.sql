-- Admin-managed third-party App download platforms.

CREATE TABLE IF NOT EXISTS app_download_platforms (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    platform_key VARCHAR(40) NOT NULL UNIQUE,
    display_name VARCHAR(80) NOT NULL,
    download_url TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_app_download_platforms_one_default
    ON app_download_platforms(is_default)
    WHERE is_default = TRUE;

CREATE INDEX IF NOT EXISTS idx_app_download_platforms_active_order
    ON app_download_platforms(is_active, is_default DESC, sort_order, updated_at DESC);
