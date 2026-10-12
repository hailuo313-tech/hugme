-- Restore deleted Telegram account identities as disabled historical records.
-- No session data is recreated and these rows can never be connected or used to send.
WITH deleted_accounts AS (
    SELECT al.sender_account_id::uuid AS id,
           MIN(al.created_at) AS first_seen_at,
           MAX(al.created_at) AS last_seen_at,
           COUNT(*) AS reference_count
    FROM attribution_links al
    WHERE al.sender_account_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
      AND NOT EXISTS (
          SELECT 1 FROM telegram_accounts ta
          WHERE ta.id::text = al.sender_account_id
      )
    GROUP BY al.sender_account_id
)
INSERT INTO telegram_accounts (
    id, phone, session_string, status, is_active, is_bot,
    display_name, error_message, metadata, created_at, updated_at
)
SELECT id,
       'arc-' || left(replace(id::text, '-', ''), 16),
       '',
       'banned',
       false,
       false,
       '历史已删除账号 · ' || left(id::text, 8),
       '账号主体已删除；从历史业务记录恢复，仅供用户迁移',
       jsonb_build_object(
           'archived_deleted', true,
           'recovered_from', 'attribution_links',
           'first_reference_at', first_seen_at,
           'last_reference_at', last_seen_at,
           'reference_count', reference_count
       ),
       first_seen_at,
       NOW()
FROM deleted_accounts
ON CONFLICT (id) DO NOTHING;
