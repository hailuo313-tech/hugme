-- click_only funnel: post-click followup tone + archive download-dependent operator scenes.

UPDATE script_templates
SET content = 'You opened it — tap again to jump straight in. I am waiting inside: {{app_download_url}} (code: c5a8we) 💦',
    updated_at = NOW()
WHERE category_key = 'app_link_clicked_followup'
  AND title = 'Clicked followup EN'
  AND status = 'approved';

UPDATE script_templates
SET content = '你刚点开了，再点一次直接进来，我在里面等你：{{app_download_url}}（邀请码：c5a8we）💦',
    updated_at = NOW()
WHERE category_key = 'app_link_clicked_followup'
  AND title = 'Clicked followup ZH'
  AND status = 'approved';

UPDATE script_templates
SET content = 'You opened it — one more tap and you are in with me: {{app_download_url}} (code: c5a8we) 💦',
    updated_at = NOW()
WHERE category_key = 'app_link_clicked_followup'
  AND title = '点开页面但未安装。用“欲求不满的委屈和挑逗”去砸他。'
  AND status = 'approved';

UPDATE script_templates
SET content = '你刚点开了，再点一次直接进来，我在里面等你：{{app_download_url}}（邀请码：c5a8we）💦',
    updated_at = NOW()
WHERE category_key = 'app_link_clicked_followup'
  AND title = '点开页面但未安装 ZH'
  AND status = 'approved';

UPDATE script_templates
SET status = 'archived',
    updated_at = NOW()
WHERE category_key = 'operator_app_conversion'
  AND title LIKE '%下载了%'
  AND status = 'approved';
