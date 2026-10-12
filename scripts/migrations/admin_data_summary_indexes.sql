-- Speed up /admin/data attribution summary reads.
-- Run with psql directly; CREATE INDEX CONCURRENTLY must not be wrapped in a transaction.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_attr_events_created_tracking_type_user
    ON attribution_events (created_at DESC, tracking_id, event_type, user_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_attr_links_sent_or_created_tracking
    ON attribution_links ((COALESCE(sent_at, created_at)), tracking_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_messages_sender_created_conversation
    ON messages (sender_type, created_at DESC, conversation_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_broadcast_jobs_created_trigger_status
    ON call_broadcast_jobs (created_at DESC, trigger_source, status, chat_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_message_schedules_nurture_video_created
    ON message_schedules (created_at DESC, user_id, status, sent_at)
    WHERE metadata->>'delivery_mode' = 'app_download_nurture'
      AND COALESCE(metadata->>'nurture_kind', '') = 'video_chat';

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_message_schedules_nurture_video_conversation
    ON message_schedules ((NULLIF(metadata->>'conversation_id', '')), created_at DESC)
    WHERE metadata->>'delivery_mode' = 'app_download_nurture'
      AND COALESCE(metadata->>'nurture_kind', '') = 'video_chat';

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_message_schedules_nurture_video_status
    ON message_schedules (status, send_at, sent_at, user_id, created_at DESC)
    WHERE metadata->>'delivery_mode' = 'app_download_nurture'
      AND COALESCE(metadata->>'nurture_kind', '') = 'video_chat';

ANALYZE attribution_events;
ANALYZE attribution_links;
ANALYZE messages;
ANALYZE call_broadcast_jobs;
ANALYZE message_schedules;
