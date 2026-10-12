-- Operator may waive post-inbound-video expert-only gate per conversation.
ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS post_inbound_video_expert_waived_at TIMESTAMP NULL;
