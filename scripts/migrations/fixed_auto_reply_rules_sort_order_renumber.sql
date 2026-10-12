-- Renumber fixed_auto_reply_rules.sort_order to 1..N by execution timeline
-- (delay_seconds ASC, then created_at ASC). Safe to re-run: always recomputes ranks.

WITH ranked AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            ORDER BY delay_seconds ASC, created_at ASC, id ASC
        ) AS new_sort
    FROM fixed_auto_reply_rules
)
UPDATE fixed_auto_reply_rules AS r
SET sort_order = ranked.new_sort,
    updated_at = NOW()
FROM ranked
WHERE r.id = ranked.id;
