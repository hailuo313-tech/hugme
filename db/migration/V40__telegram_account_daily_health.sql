ALTER TABLE video_reinvite_account_state
ADD COLUMN IF NOT EXISTS health_check_status varchar(32) NOT NULL DEFAULT 'pending',
ADD COLUMN IF NOT EXISTS last_health_check_at timestamptz,
ADD COLUMN IF NOT EXISTS last_health_error text,
ADD COLUMN IF NOT EXISTS health_check_attempts integer NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS first_connected_at timestamptz,
ADD COLUMN IF NOT EXISTS is_new_account boolean NOT NULL DEFAULT false;

UPDATE video_reinvite_account_state SET
  first_connected_at=COALESCE(first_connected_at,platform_connected_at,NOW()),
  is_new_account=COALESCE(platform_connected_at,NOW())>=NOW()-INTERVAL '1 day';

CREATE TABLE IF NOT EXISTS telegram_account_health_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_type varchar(24) NOT NULL,
  started_at timestamptz NOT NULL DEFAULT NOW(),
  completed_at timestamptz,
  checked_count integer NOT NULL DEFAULT 0,
  healthy_count integer NOT NULL DEFAULT 0,
  new_count integer NOT NULL DEFAULT 0,
  pending_count integer NOT NULL DEFAULT 0,
  banned_count integer NOT NULL DEFAULT 0,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_tg_health_runs_started ON telegram_account_health_runs(started_at DESC);
