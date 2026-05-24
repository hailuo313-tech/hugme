-- App-download conversion funnel script categories and approved starter templates.

INSERT INTO script_template_categories (key, display_name, description, sort_order)
VALUES
    ('app_download_first_push', 'App download first push', 'First soft CTA to move an unpaid chat user into the third-party App.', 60),
    ('app_download_after_warmup', 'App download after warmup', 'CTA after the user has replied enough to preserve momentum.', 61),
    ('app_download_direct_cta', 'App download direct CTA', 'Direct link response when the user asks where or how to continue.', 62),
    ('app_download_objection', 'App download objection', 'Handles download friction, hesitation, or not wanting another App.', 63),
    ('trust_reassurance', 'Trust reassurance', 'Explains why the link/App is used without pressure or false claims.', 64),
    ('app_link_clicked_followup', 'Clicked but not downloaded', 'Follow-up after link click without App download.', 65),
    ('app_downloaded_not_registered', 'Downloaded but not registered', 'Follow-up after App download without registration.', 66),
    ('app_registered_not_paid', 'Registered but not paid', 'Follow-up after registration without in-App payment.', 67),
    ('operator_app_conversion', 'Operator App conversion', 'Manual/higher-value handoff copy for T1 or high-intent users.', 68)
ON CONFLICT (key) DO UPDATE
SET display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    sort_order = EXCLUDED.sort_order,
    is_active = TRUE,
    updated_at = NOW();

INSERT INTO script_templates (
    id, category_key, title, language, channel, platform, user_level, chat_route,
    persona_slug, hook, content, variables, safety_tags, status
)
VALUES
    ('12000000-0000-0000-0000-000000000001','app_download_first_push','First App push EN','en','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','We can keep going, but the full experience is in the app. Tap here and I will wait for you there: {{app_download_url}}','["app_download_url"]','["app_download_conversion","link_click"]','approved'),
    ('12000000-0000-0000-0000-000000000002','app_download_first_push','First App push ZH','zh','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','我们可以继续聊，但完整体验在 App 里。点这里进去，我在那边等你：{{app_download_url}}','["app_download_url"]','["app_download_conversion","link_click"]','approved'),
    ('12000000-0000-0000-0000-000000000003','app_download_after_warmup','Warm App push EN','en','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','We just got the mood going. Do not let it stop here. Open the app and we will continue: {{app_download_url}}','["app_download_url"]','["app_download_conversion","warm_user","link_click"]','approved'),
    ('12000000-0000-0000-0000-000000000004','app_download_after_warmup','Warm App push ZH','zh','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','这段感觉刚起来，别断在这里。打开 App，我们继续：{{app_download_url}}','["app_download_url"]','["app_download_conversion","warm_user","link_click"]','approved'),
    ('12000000-0000-0000-0000-000000000005','app_download_direct_cta','Direct App CTA EN','en','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','Yes, here is the place to continue. Open it and come back to me inside the app: {{app_download_url}}','["app_download_url"]','["app_download_conversion","direct_cta","link_click"]','approved'),
    ('12000000-0000-0000-0000-000000000006','app_download_direct_cta','Direct App CTA ZH','zh','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','可以，继续入口在这里。打开后进 App，我们接着聊：{{app_download_url}}','["app_download_url"]','["app_download_conversion","direct_cta","link_click"]','approved'),
    ('12000000-0000-0000-0000-000000000007','app_download_objection','Download objection EN','en','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','I get it, downloading is one more step. If you are a little curious about me, this is how we keep the chat from breaking: {{app_download_url}}','["app_download_url"]','["app_download_conversion","objection","link_click"]','approved'),
    ('12000000-0000-0000-0000-000000000008','app_download_objection','Download objection ZH','zh','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','我懂，下载确实多一步。但如果你对我有点兴趣，这一步就是把刚才的聊天接上：{{app_download_url}}','["app_download_url"]','["app_download_conversion","objection","link_click"]','approved'),
    ('12000000-0000-0000-0000-000000000009','trust_reassurance','Trust reassurance EN','en','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','This is not a random ad. This is the app link for the full chat experience, so we can continue properly: {{app_download_url}}','["app_download_url"]','["app_download_conversion","trust","link_click"]','approved'),
    ('12000000-0000-0000-0000-000000000010','trust_reassurance','Trust reassurance ZH','zh','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','这不是乱点广告，是完整聊天体验的 App 入口。进去后我们才能更顺地继续：{{app_download_url}}','["app_download_url"]','["app_download_conversion","trust","link_click"]','approved'),
    ('12000000-0000-0000-0000-000000000011','app_link_clicked_followup','Clicked followup EN','en','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','Did it open? If the page loaded, install it and I will keep the same vibe for you inside the app.','[]','["app_download_conversion","clicked_not_downloaded"]','approved'),
    ('12000000-0000-0000-0000-000000000012','app_link_clicked_followup','Clicked followup ZH','zh','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','点开了吗？如果页面出来了，直接安装就行，我会在 App 里按刚才的感觉继续。','[]','["app_download_conversion","clicked_not_downloaded"]','approved'),
    ('12000000-0000-0000-0000-000000000013','app_downloaded_not_registered','Downloaded not registered EN','en','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','If it is installed, you are one step away. Register inside the app and we can continue without starting over.','[]','["app_download_conversion","downloaded_not_registered"]','approved'),
    ('12000000-0000-0000-0000-000000000014','app_downloaded_not_registered','Downloaded not registered ZH','zh','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','装好了就差一步。进 App 注册一下，我们就能不用重新开始，直接接着聊。','[]','["app_download_conversion","downloaded_not_registered"]','approved'),
    ('12000000-0000-0000-0000-000000000015','app_registered_not_paid','Registered not paid EN','en','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','Now you are in the right place. If you want the full version of what we started, follow the app unlock prompt and I will continue from there.','[]','["app_download_conversion","registered_not_paid"]','approved'),
    ('12000000-0000-0000-0000-000000000016','app_registered_not_paid','Registered not paid ZH','zh','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','你已经进到正确地方了。想继续刚才没展开的部分，就按 App 里的提示解锁，我会从那里接上。','[]','["app_download_conversion","registered_not_paid"]','approved'),
    ('12000000-0000-0000-0000-000000000017','operator_app_conversion','Operator App conversion EN','en','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','You are already at the good part. Open the app, and I will keep this exact direction for you instead of making you start cold again: {{app_download_url}}','["app_download_url"]','["app_download_conversion","operator","t1_priority"]','approved'),
    ('12000000-0000-0000-0000-000000000018','operator_app_conversion','Operator App conversion ZH','zh','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','你已经聊到有感觉的位置了。打开 App，我会按这个方向继续，不让你重新冷启动：{{app_download_url}}','["app_download_url"]','["app_download_conversion","operator","t1_priority"]','approved')
ON CONFLICT (id) DO UPDATE
SET category_key = EXCLUDED.category_key,
    title = EXCLUDED.title,
    language = EXCLUDED.language,
    channel = EXCLUDED.channel,
    platform = EXCLUDED.platform,
    user_level = EXCLUDED.user_level,
    chat_route = EXCLUDED.chat_route,
    persona_slug = EXCLUDED.persona_slug,
    hook = EXCLUDED.hook,
    content = EXCLUDED.content,
    variables = EXCLUDED.variables,
    safety_tags = EXCLUDED.safety_tags,
    status = EXCLUDED.status,
    updated_at = NOW();
