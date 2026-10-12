ALTER TABLE video_reinvite_settings
ADD COLUMN IF NOT EXISTS daily_account_limit integer NOT NULL DEFAULT 15
CHECK (daily_account_limit BETWEEN 1 AND 50);

UPDATE video_reinvite_settings
SET min_interval_seconds=180,
    max_interval_seconds=180,
    hourly_account_limit=15,
    daily_account_limit=15,
    send_hour_start=10,
    send_hour_end=22,
    updated_at=NOW()
WHERE id=1;

CREATE TABLE IF NOT EXISTS video_reinvite_account_state (
    account_id uuid PRIMARY KEY REFERENCES telegram_accounts(id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused')),
    consecutive_failures integer NOT NULL DEFAULT 0,
    paused_at timestamptz,
    pause_reason text,
    last_success_at timestamptz,
    last_failure_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE video_reinvite_account_state IS 'Per-account circuit breaker for safe video reinvitation sending';
