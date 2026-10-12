ALTER TABLE video_reinvite_settings
ADD COLUMN IF NOT EXISTS next_global_send_at timestamptz;

