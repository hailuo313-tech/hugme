-- Script template media attachments for images, videos, voice, and audio.

CREATE TABLE IF NOT EXISTS script_template_assets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    script_template_id UUID NOT NULL REFERENCES script_templates(id) ON DELETE CASCADE,
    asset_type VARCHAR(20) NOT NULL CHECK (asset_type IN ('image', 'video', 'voice', 'audio')),
    asset_url TEXT NOT NULL,
    storage_path TEXT,
    original_filename VARCHAR(255),
    mime_type VARCHAR(120),
    file_size_bytes BIGINT,
    caption TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_script_template_assets_template_order
    ON script_template_assets(script_template_id, is_active, sort_order, created_at);

