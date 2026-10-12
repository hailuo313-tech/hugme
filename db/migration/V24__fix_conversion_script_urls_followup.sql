-- V24: Remaining script-library gaps after V23 audit.

-- Trust scenes still missing tracked link placeholder.
UPDATE script_templates
SET content = TRIM(content) || ' Tap here now: {{app_download_url}} (code: c5a8we)',
    updated_at = NOW()
WHERE category_key = 'trust_reassurance'
  AND status = 'approved'
  AND content !~* '\{\{app_download_url\}\}'
  AND content !~* 'https?://'
  AND LENGTH(TRIM(content)) > 0;

-- Archive legacy duplicate video keyword row (blocked terms / stale copy).
UPDATE script_templates
SET status = 'archived',
    updated_at = NOW()
WHERE category_key = 'app_download_first_push'
  AND title = '用户聊天中想要看本人视频的关键词'
  AND status = 'approved'
  AND content ~* '(longer one|another clip|play more)';

-- Dedupe duplicate clicked-followup scene rows (keep oldest approved).
UPDATE script_templates
SET status = 'archived',
    updated_at = NOW()
WHERE id IN (
    SELECT id
    FROM (
        SELECT
            id,
            ROW_NUMBER() OVER (
                PARTITION BY category_key, title, language
                ORDER BY created_at ASC, id ASC
            ) AS rn
        FROM script_templates
        WHERE category_key = 'app_link_clicked_followup'
          AND title = '点开页面但未安装。用“欲求不满的委屈和挑逗”去砸他。'
          AND status = 'approved'
    ) ranked
    WHERE rn > 1
);
