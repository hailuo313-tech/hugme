BEGIN;

ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS device_os VARCHAR(20);
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS device_user_agent TEXT;
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS device_first_detected_at TIMESTAMPTZ;
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS device_last_detected_at TIMESTAMPTZ;

UPDATE attribution_events
SET device_os = CASE
  WHEN user_agent ~* 'Android' THEN 'Android'
  WHEN user_agent ~* 'iPhone|iPad|iPod' THEN 'iOS'
  WHEN user_agent ~* 'Windows NT|Macintosh|X11|CrOS' THEN 'Desktop'
  ELSE 'Unknown'
END
WHERE event_type = 'click' AND (device_os IS NULL OR device_os = '');

WITH detected AS (
  SELECT user_id,
    (array_agg(device_os ORDER BY created_at DESC))[1] AS device_os,
    (array_agg(user_agent ORDER BY created_at DESC))[1] AS user_agent,
    MIN(created_at) AS first_detected_at,
    MAX(created_at) AS last_detected_at
  FROM attribution_events
  WHERE event_type = 'click' AND user_id IS NOT NULL
    AND device_os IN ('iOS', 'Android', 'Desktop')
  GROUP BY user_id
)
INSERT INTO user_profiles (
  user_id, device_os, device_user_agent,
  device_first_detected_at, device_last_detected_at, updated_at
)
SELECT user_id, device_os, user_agent, first_detected_at, last_detected_at, NOW()
FROM detected
ON CONFLICT (user_id) DO UPDATE
SET device_os = EXCLUDED.device_os,
    device_user_agent = EXCLUDED.device_user_agent,
    device_first_detected_at = COALESCE(user_profiles.device_first_detected_at, EXCLUDED.device_first_detected_at),
    device_last_detected_at = EXCLUDED.device_last_detected_at,
    updated_at = NOW();

CREATE INDEX IF NOT EXISTS idx_user_profiles_device_os ON user_profiles (device_os);
COMMIT;
