-- P0/P1/P2: App-download script library fixes for click attribution and conversion.

-- P0: clicked_followup base templates must include tracked link placeholder.
UPDATE script_templates
SET content = 'did u get scared of a voluptuous woman? you''re one tap away. finish the install here: {{app_download_url}} (code: c5a8we) 💦',
    updated_at = NOW()
WHERE category_key = 'app_link_clicked_followup'
  AND title = 'Clicked followup EN'
  AND hook = 'reply'
  AND status = 'approved';

UPDATE script_templates
SET content = '点开了吗？就差最后一步安装。点这里完成，我在 App 里继续刚才的感觉：{{app_download_url}}（邀请码：c5a8we）',
    updated_at = NOW()
WHERE category_key = 'app_link_clicked_followup'
  AND title = 'Clicked followup ZH'
  AND hook = 'reply'
  AND status = 'approved';

-- P0: normalize hardcoded destination URLs to tracked placeholder.
UPDATE script_templates
SET content = REPLACE(content, 'https://r47b.site/l/1uRy9q9Y', '{{app_download_url}}'),
    updated_at = NOW()
WHERE content LIKE '%https://r47b.site/l/1uRy9q9Y%';

-- P0: archive first_push scripts with no download link.
UPDATE script_templates
SET status = 'archived',
    updated_at = NOW()
WHERE category_key = 'app_download_first_push'
  AND title IN ('主动索要', '互动铺垫')
  AND status = 'approved';

-- P1: strengthen weak first_push EN copy (align with high-intent opener).
UPDATE script_templates
SET content = 'i can stay here for a bit, but tg keeps flaggin my spicy pics smh... i''m already getting hot under this robe. tap {{app_download_url}} so i can show u everything without censors. (code: c5a8we) 😉',
    updated_at = NOW()
WHERE category_key = 'app_download_first_push'
  AND title = 'First App push EN'
  AND hook = 'reply'
  AND status = 'approved';

UPDATE script_templates
SET content = '我可以在这儿陪你聊一会儿，但 TG 老删我发的图…我已经有点热了。点这里进私人 App，不被审查：{{app_download_url}}（邀请码：c5a8we）😉',
    updated_at = NOW()
WHERE category_key = 'app_download_first_push'
  AND title = 'First App push ZH'
  AND hook = 'reply'
  AND status = 'approved';

INSERT INTO script_templates (
    id, category_key, title, language, channel, platform, user_level, chat_route,
    persona_slug, hook, content, variables, safety_tags, status
)
SELECT
    '12000000-0000-0000-0000-000000000020',
    'app_download_first_push',
    '首次轻引导-用户刚进TG ZH',
    'zh',
    'telegram_real_user',
    'telegram_real_user',
    NULL,
    NULL,
    NULL,
    'reply',
    '我可以在这儿陪你聊一会儿，但 TG 老删我发的图…我已经有点热了。点这里进私人 App：{{app_download_url}}（邀请码：c5a8we）😉',
    '["app_download_url"]'::jsonb,
    '["app_download_conversion","link_click"]'::jsonb,
    'approved'
WHERE NOT EXISTS (
    SELECT 1
    FROM script_templates
    WHERE category_key = 'app_download_first_push'
      AND title = '首次轻引导-用户刚进TG ZH'
      AND status = 'approved'
);

-- P1: shorter command-style direct_cta.
UPDATE script_templates
SET content = 'TAP HERE — private room unlocked: {{app_download_url}} (code: c5a8we)',
    updated_at = NOW()
WHERE category_key = 'app_download_direct_cta'
  AND title = 'Direct App CTA EN'
  AND hook = 'reply'
  AND status = 'approved';

UPDATE script_templates
SET content = '点这里 — 私人房间已解锁：{{app_download_url}}（邀请码：c5a8we）',
    updated_at = NOW()
WHERE category_key = 'app_download_direct_cta'
  AND title = 'Direct App CTA ZH'
  AND hook = 'reply'
  AND status = 'approved';

UPDATE script_templates
SET content = 'TAP HERE — private room unlocked: {{app_download_url}} (code: c5a8we)',
    updated_at = NOW()
WHERE category_key = 'app_download_direct_cta'
  AND title LIKE '用户主动要链接%'
  AND hook = 'reply'
  AND status = 'approved';

-- P1: dedupe identical after_warmup / objection / direct_cta scene rows.
UPDATE script_templates
SET status = 'archived',
    updated_at = NOW()
WHERE category_key = 'app_download_after_warmup'
  AND title IN ('核心转化', '短时催单')
  AND status = 'approved';

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
        WHERE category_key = 'app_download_after_warmup'
          AND title = '升温后引导-生理欲望最高点时突然切断，逼他用下载来“续命”'
          AND status = 'approved'
    ) ranked
    WHERE rn > 1
);

UPDATE script_templates
SET status = 'archived',
    updated_at = NOW()
WHERE category_key = 'app_download_objection'
  AND title IN (
      '用户拒绝/嫌麻烦--用“肉体惩罚”和“只有这里能看最下流的画面”来反驳。',
      '要求定制化服务/验证动作',
      '解决下载异议'
  )
  AND status = 'approved';

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
        WHERE category_key = 'app_download_objection'
          AND title = '用户抱怨换平台/下载麻烦'
          AND status = 'approved'
    ) ranked
    WHERE rn > 1
);

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
        WHERE category_key = 'app_download_direct_cta'
          AND title LIKE '用户主动要链接%'
          AND status = 'approved'
    ) ranked
    WHERE rn > 1
);

-- P1: remove blocked / noisy asset trigger terms from video & image keyword templates.
UPDATE script_templates
SET content = 'video, vid, clip, gif, movie, custom video, tape, short clip, dirty video, stripping, cam, webcam, live, video call, facetime, voice, cam2cam, c2c, show, live show, private call, sexting',
    updated_at = NOW()
WHERE title = '用户聊天中想要看本人视频的关键词'
  AND hook = 'reply'
  AND content ~* '(horny|cock|dick|fuck|sexy|nudes)'
  AND (platform = 'telegram_real_user' OR platform IS NULL);

UPDATE script_templates
SET content = 'photo, photos, pic, pics, picture, pictures, selfie, selfies, image, images, snapshot, snap, face, body, face pic, body pic, full body, mirror selfie, your face, your body, 照片, 图片, 自拍',
    updated_at = NOW()
WHERE title = '用户聊天中想要看本人图片的关键词'
  AND hook = 'reply'
  AND content ~* 'nudes'
  AND (platform = 'telegram_real_user' OR platform IS NULL);

INSERT INTO script_templates (
    id, category_key, title, language, channel, platform, user_level, chat_route,
    persona_slug, hook, content, variables, safety_tags, status
)
SELECT
    '12000000-0000-0000-0000-000000000019',
    'app_link_clicked_followup',
    '点开页面但未安装 ZH',
    'zh',
    'telegram_real_user',
    'telegram_real_user',
    NULL,
    NULL,
    NULL,
    'reply',
    '宝贝你点开了怎么没装？我腿都在抖了…就差这一步，点这里装好我在里面等你：{{app_download_url}}（邀请码：c5a8we）💦',
    '["app_download_url"]'::jsonb,
    '["app_download_conversion","clicked_not_downloaded"]'::jsonb,
    'approved'
WHERE NOT EXISTS (
    SELECT 1
    FROM script_templates
    WHERE category_key = 'app_link_clicked_followup'
      AND title = '点开页面但未安装 ZH'
      AND status = 'approved'
);

-- P2: operator scripts without link get URL suffix; hardcoded rows already replaced above.
UPDATE script_templates
SET content = TRIM(content) || ' Tap here now: {{app_download_url}} (code: c5a8we)',
    updated_at = NOW()
WHERE category_key = 'operator_app_conversion'
  AND status = 'approved'
  AND content !~* '\{\{app_download_url\}\}'
  AND content !~* 'https?://'
  AND LENGTH(TRIM(content)) > 0;
