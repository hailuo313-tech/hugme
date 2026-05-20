-- P1-09 sketch: telegram_accounts with Fernet session_ciphertext

CREATE TYPE telegram_account_status AS ENUM (
    'pending', 'active', 'disabled', 'banned'
);

CREATE TABLE telegram_accounts (
    account_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    label               TEXT NOT NULL DEFAULT '',
    api_id              INTEGER NOT NULL,
    session_ciphertext  BYTEA NOT NULL,
    status              telegram_account_status NOT NULL DEFAULT 'pending',
    last_connected_at   TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_telegram_accounts_status ON telegram_accounts (status);
