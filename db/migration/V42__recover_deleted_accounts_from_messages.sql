-- Recover deleted Telegram account identities that remain in original assistant
-- messages but were absent from the attribution-link based archive catalogue.
WITH recovered AS (
    SELECT
        m.sender_id::uuid AS account_id,
        COUNT(*) AS message_count,
        COUNT(DISTINCT m.conversation_id) AS conversation_count,
        MIN(m.created_at) AS first_reference_at,
        MAX(m.created_at) AS last_reference_at
    FROM messages m
    LEFT JOIN telegram_accounts a ON a.id::text = m.sender_id
    WHERE m.sender_type = 'assistant'
      AND m.sender_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
      AND a.id IS NULL
    GROUP BY m.sender_id
)
INSERT INTO telegram_accounts (
    id, phone, session_string, status, is_active, display_name, metadata,
    created_at, updated_at
)
SELECT
    r.account_id,
    'arc-' || LEFT(REPLACE(r.account_id::text, '-', ''), 16),
    '',
    'banned',
    FALSE,
    '历史已删除账号 · ' || LEFT(r.account_id::text, 8),
    jsonb_build_object(
        'archived_deleted', TRUE,
        'recovered_from', 'messages',
        'message_count', r.message_count,
        'reference_count', r.conversation_count,
        'first_reference_at', r.first_reference_at,
        'last_reference_at', r.last_reference_at
    ),
    r.first_reference_at,
    NOW()
FROM recovered r
ON CONFLICT (id) DO NOTHING;
