-- Attribute real inbound Telegram messages to the account that received them.
-- This prevents group/channel participants and profile-cache rows from being
-- reported as one-to-one Telegram users.

ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS telegram_account_id UUID
    REFERENCES telegram_accounts(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_messages_tg_account_inbound_created
    ON messages (telegram_account_id, created_at DESC, conversation_id)
    WHERE sender_type = 'user' AND telegram_account_id IS NOT NULL;

-- Conservative historical recovery: only attribute an inbound message when
-- that conversation has an assistant message from exactly one TG account.
-- Ambiguous conversations remain NULL instead of inflating real-user counts.
WITH conversation_accounts AS (
    SELECT
        conversation_id,
        MIN(m.sender_id)::uuid AS account_id
    FROM messages m
    JOIN telegram_accounts ta ON ta.id::text = m.sender_id
    WHERE sender_type = 'assistant'
      AND m.sender_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    GROUP BY conversation_id
    HAVING COUNT(DISTINCT m.sender_id) = 1
)
UPDATE messages AS inbound
SET telegram_account_id = ca.account_id
FROM conversation_accounts ca
WHERE inbound.conversation_id = ca.conversation_id
  AND inbound.sender_type = 'user'
  AND inbound.telegram_account_id IS NULL;
