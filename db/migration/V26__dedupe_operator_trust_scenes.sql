-- Dedupe duplicate operator/trust scene rows (keep oldest approved per title).

UPDATE script_templates
SET status = 'archived',
    updated_at = NOW()
WHERE id IN (
    SELECT id
    FROM (
        SELECT
            id,
            ROW_NUMBER() OVER (
                PARTITION BY category_key, title
                ORDER BY created_at ASC, id ASC
            ) AS rn
        FROM script_templates
        WHERE status = 'approved'
          AND category_key IN ('operator_app_conversion', 'trust_reassurance')
    ) ranked
    WHERE rn > 1
);
