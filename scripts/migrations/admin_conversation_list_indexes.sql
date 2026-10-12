-- Speed up /admin/conversations list tabs and detail previews.
-- Safe to run repeatedly; indexes are created concurrently to avoid blocking writes.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_conversations_state_order
  ON conversations (state, handoff_count DESC, last_message_at DESC, created_at DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_conversations_channel_state
  ON conversations (channel, state);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_conversations_user_recent
  ON conversations (user_id, last_message_at DESC, created_at DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_messages_conversation_created_desc
  ON messages (conversation_id, created_at DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_messages_conversation_sender_created
  ON messages (conversation_id, sender_type, created_at);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_handoff_tasks_video_pending
  ON handoff_tasks (conversation_id, trigger_reason, status)
  WHERE closed_at IS NULL;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_broadcast_jobs_inbound_completed
  ON call_broadcast_jobs (chat_id, trigger_source, status, created_at DESC)
  WHERE status = 'completed';
