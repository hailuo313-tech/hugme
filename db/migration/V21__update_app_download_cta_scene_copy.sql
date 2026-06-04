-- Update app-download CTA scene copy to the approved four-scenario wording.

UPDATE script_templates
SET content = 'Let''s chat on my private app instead, way safer than here. Grab it real quick and text me: {{app_download_url}} (Enter code: c5a8we)',
    updated_at = NOW()
WHERE category_key = 'app_download_direct_cta'
  AND language = 'en'
  AND hook = 'reply'
  AND (platform = 'telegram_real_user' OR platform IS NULL);

UPDATE script_templates
SET content = '去我的私人App上聊吧，比这里安全多了。快去下一个然后发信息给我：{{app_download_url}} 输入邀请码：c5a8we',
    updated_at = NOW()
WHERE category_key = 'app_download_direct_cta'
  AND language = 'zh'
  AND hook = 'reply'
  AND (platform = 'telegram_real_user' OR platform IS NULL);

UPDATE script_templates
SET content = 'Btw, my TG is lagging crazy right now and missing texts. Drop me a line on my main app here, it''s free and way faster: {{app_download_url}} (Use code: c5a8we)',
    updated_at = NOW()
WHERE category_key = 'app_download_after_warmup'
  AND language = 'en'
  AND hook = 'reply'
  AND (platform = 'telegram_real_user' OR platform IS NULL);

UPDATE script_templates
SET content = '顺便说下，我TG现在卡得要死一直在漏消息。去我的主力App上找我吧，免费而且快得多：{{app_download_url}} 邀请码：c5a8we',
    updated_at = NOW()
WHERE category_key = 'app_download_after_warmup'
  AND language = 'zh'
  AND hook = 'reply'
  AND (platform = 'telegram_real_user' OR platform IS NULL);

UPDATE script_templates
SET content = 'I only text close friends on my private encrypted app because TG keeps censoring our topics anyway. Takes like 15 seconds to set up, come over: {{app_download_url}}',
    updated_at = NOW()
WHERE category_key = 'app_download_objection'
  AND language = 'en'
  AND hook = 'reply'
  AND (platform = 'telegram_real_user' OR platform IS NULL);

UPDATE script_templates
SET content = '我只在我的私人加密App上和熟人聊天，反正TG老是审查咱们的话题。15秒就设置好了，快过来：{{app_download_url}}',
    updated_at = NOW()
WHERE category_key = 'app_download_objection'
  AND language = 'zh'
  AND hook = 'reply'
  AND (platform = 'telegram_real_user' OR platform IS NULL);
