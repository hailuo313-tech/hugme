ALTER TABLE video_reinvite_account_state
DROP CONSTRAINT IF EXISTS video_reinvite_account_state_status_check;
ALTER TABLE video_reinvite_account_state
ADD CONSTRAINT video_reinvite_account_state_status_check
CHECK (status IN ('active','observing','paused'));

ALTER TABLE video_reinvite_account_state
ADD COLUMN IF NOT EXISTS platform_connected_at timestamptz,
ADD COLUMN IF NOT EXISTS tier smallint NOT NULL DEFAULT 1 CHECK (tier BETWEEN 1 AND 4),
ADD COLUMN IF NOT EXISTS tier_locked boolean NOT NULL DEFAULT false,
ADD COLUMN IF NOT EXISTS tier_changed_at timestamptz NOT NULL DEFAULT NOW(),
ADD COLUMN IF NOT EXISTS effective_daily_limit integer NOT NULL DEFAULT 15,
ADD COLUMN IF NOT EXISTS effective_min_interval_seconds integer NOT NULL DEFAULT 180,
ADD COLUMN IF NOT EXISTS resume_at timestamptz,
ADD COLUMN IF NOT EXISTS seven_day_attempts integer NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS seven_day_successes integer NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS seven_day_success_rate numeric(6,5) NOT NULL DEFAULT 1,
ADD COLUMN IF NOT EXISTS last_peer_flood_at timestamptz,
ADD COLUMN IF NOT EXISTS last_restricted_at timestamptz;

INSERT INTO video_reinvite_account_state (
  account_id,platform_connected_at,tier,tier_changed_at,
  effective_daily_limit,effective_min_interval_seconds
)
SELECT a.id,
       COALESCE(NULLIF(a.metadata->>'platform_connected_at','')::timestamptz,
                a.created_at AT TIME ZONE 'UTC',a.last_connected_at AT TIME ZONE 'UTC',NOW()),
       CASE WHEN CURRENT_DATE-(COALESCE(a.created_at,a.last_connected_at,NOW() AT TIME ZONE 'UTC'))::date <= 15 THEN 1
            WHEN CURRENT_DATE-(COALESCE(a.created_at,a.last_connected_at,NOW() AT TIME ZONE 'UTC'))::date <= 30 THEN 2
            WHEN CURRENT_DATE-(COALESCE(a.created_at,a.last_connected_at,NOW() AT TIME ZONE 'UTC'))::date <= 60 THEN 3 ELSE 4 END,
       NOW()-INTERVAL '3 days',
       CASE WHEN CURRENT_DATE-(COALESCE(a.created_at,a.last_connected_at,NOW() AT TIME ZONE 'UTC'))::date <= 15 THEN 15
            WHEN CURRENT_DATE-(COALESCE(a.created_at,a.last_connected_at,NOW() AT TIME ZONE 'UTC'))::date <= 30 THEN 25
            WHEN CURRENT_DATE-(COALESCE(a.created_at,a.last_connected_at,NOW() AT TIME ZONE 'UTC'))::date <= 60 THEN 40 ELSE 60 END,
       CASE WHEN CURRENT_DATE-(COALESCE(a.created_at,a.last_connected_at,NOW() AT TIME ZONE 'UTC'))::date <= 15 THEN 180
            WHEN CURRENT_DATE-(COALESCE(a.created_at,a.last_connected_at,NOW() AT TIME ZONE 'UTC'))::date <= 30 THEN 150
            WHEN CURRENT_DATE-(COALESCE(a.created_at,a.last_connected_at,NOW() AT TIME ZONE 'UTC'))::date <= 60 THEN 120 ELSE 90 END
FROM telegram_accounts a
WHERE a.is_active AND a.status='connected'
ON CONFLICT(account_id) DO UPDATE SET
  platform_connected_at=COALESCE(video_reinvite_account_state.platform_connected_at,EXCLUDED.platform_connected_at);

UPDATE video_reinvite_account_state s SET
  platform_connected_at=COALESCE(s.platform_connected_at,a.created_at AT TIME ZONE 'UTC',NOW()),
  tier_changed_at=LEAST(s.tier_changed_at,NOW()-INTERVAL '3 days')
FROM telegram_accounts a WHERE a.id=s.account_id;

CREATE INDEX IF NOT EXISTS idx_video_reinvite_account_tier
ON video_reinvite_account_state(status,tier,effective_daily_limit);
