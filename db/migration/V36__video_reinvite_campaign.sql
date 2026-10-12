CREATE TABLE IF NOT EXISTS video_reinvite_settings (
    id smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    enabled boolean NOT NULL DEFAULT false,
    invitation_message text NOT NULL,
    send_hour_start smallint NOT NULL DEFAULT 10 CHECK (send_hour_start BETWEEN 0 AND 23),
    send_hour_end smallint NOT NULL DEFAULT 22 CHECK (send_hour_end BETWEEN 1 AND 24),
    max_rounds smallint NOT NULL DEFAULT 3 CHECK (max_rounds BETWEEN 1 AND 5),
    round_days integer[] NOT NULL DEFAULT ARRAY[1,3,7],
    min_interval_seconds integer NOT NULL DEFAULT 45 CHECK (min_interval_seconds >= 30),
    max_interval_seconds integer NOT NULL DEFAULT 90 CHECK (max_interval_seconds >= min_interval_seconds),
    hourly_account_limit integer NOT NULL DEFAULT 30 CHECK (hourly_account_limit BETWEEN 1 AND 60),
    updated_at timestamptz NOT NULL DEFAULT NOW()
);

INSERT INTO video_reinvite_settings (id, invitation_message)
SELECT 1, COALESCE(
    (SELECT text_content FROM fixed_auto_reply_rules
     WHERE name='3分30秒邀请视频电话' ORDER BY updated_at DESC LIMIT 1),
    'Would you like to video call me? I would love to see you. 💕'
)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS video_reinvite_jobs (
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id uuid NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    conversation_id uuid REFERENCES conversations(id) ON DELETE SET NULL,
    account_id uuid REFERENCES telegram_accounts(id) ON DELETE SET NULL,
    telegram_chat_id bigint,
    telegram_access_hash bigint,
    status text NOT NULL DEFAULT 'scheduled' CHECK (status IN (
        'scheduled','sending','sent','replied','video_success','paused',
        'unreachable','restricted','waiting_migration','stopped'
    )),
    round_number smallint NOT NULL DEFAULT 0,
    next_send_at timestamptz,
    last_sent_at timestamptz,
    replied_at timestamptz,
    video_success_at timestamptz,
    stopped_reason text,
    failure_reason text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT NOW(),
    updated_at timestamptz NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_video_reinvite_due
ON video_reinvite_jobs (next_send_at, account_id)
WHERE status='scheduled';
CREATE INDEX IF NOT EXISTS idx_video_reinvite_status
ON video_reinvite_jobs (status, updated_at DESC);

CREATE TABLE IF NOT EXISTS video_reinvite_attempts (
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id uuid NOT NULL REFERENCES video_reinvite_jobs(id) ON DELETE CASCADE,
    round_number smallint NOT NULL,
    account_id uuid REFERENCES telegram_accounts(id) ON DELETE SET NULL,
    status text NOT NULL CHECK (status IN ('sending','sent','failed','restricted','unreachable')),
    telegram_message_id bigint,
    failure_reason text,
    created_at timestamptz NOT NULL DEFAULT NOW(),
    sent_at timestamptz
);
CREATE INDEX IF NOT EXISTS idx_video_reinvite_attempt_account_time
ON video_reinvite_attempts (account_id, sent_at DESC);

COMMENT ON TABLE video_reinvite_jobs IS 'T+1/T+3/T+7 invitations for Telegram users without a successful video call';
