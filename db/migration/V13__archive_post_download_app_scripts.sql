-- The ERIS-owned funnel ends at App download. Third-party registration/payment
-- follow-up templates stay archived so operators can reference history without
-- auto-selecting them in active chat.

UPDATE script_templates
SET status = 'archived',
    updated_at = NOW()
WHERE category_key IN (
    'app_downloaded_not_registered',
    'app_registered_not_paid'
)
  AND status <> 'archived';
