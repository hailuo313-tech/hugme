-- Country -> A-F platform routes for App download links.

CREATE TABLE IF NOT EXISTS app_download_country_routes (
    country_code VARCHAR(2) PRIMARY KEY,
    platform_key VARCHAR(40) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT chk_app_download_country_code
        CHECK (country_code ~ '^[A-Z]{2}$'),
    CONSTRAINT chk_app_download_country_platform
        CHECK (platform_key IN (
            'platform_a', 'platform_b', 'platform_c',
            'platform_d', 'platform_e', 'platform_f'
        ))
);

CREATE INDEX IF NOT EXISTS idx_app_download_country_routes_platform
    ON app_download_country_routes(platform_key);
