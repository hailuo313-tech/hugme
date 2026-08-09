ALTER TABLE telegram_accounts
    ADD COLUMN IF NOT EXISTS api_credential_id uuid
    REFERENCES telegram_api_credentials(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_telegram_accounts_api_credential_id
    ON telegram_accounts(api_credential_id);
