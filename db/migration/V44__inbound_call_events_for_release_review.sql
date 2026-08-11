CREATE TABLE IF NOT EXISTS telegram_inbound_call_events (
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_id uuid NOT NULL REFERENCES telegram_accounts(id) ON DELETE CASCADE,
    chat_id bigint NOT NULL,
    event_key text NOT NULL,
    trace_id text,
    created_at timestamptz NOT NULL DEFAULT NOW(),
    UNIQUE (account_id, event_key)
);

CREATE INDEX IF NOT EXISTS idx_inbound_call_events_chat_created
    ON telegram_inbound_call_events(chat_id, created_at);

INSERT INTO telegram_inbound_call_events (
    account_id, chat_id, event_key, trace_id, created_at
)
SELECT
    j.account_id,
    j.chat_id,
    'legacy-job:' || j.id::text,
    j.trace_id,
    j.created_at
FROM call_broadcast_jobs j
JOIN telegram_accounts a ON a.id = j.account_id
WHERE j.account_id IS NOT NULL
  AND j.chat_id IS NOT NULL
  AND j.trigger_source IN ('inbound_call', 'inbound_operator_review')
ON CONFLICT (account_id, event_key) DO NOTHING;
