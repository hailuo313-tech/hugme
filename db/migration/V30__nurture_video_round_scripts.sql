-- Nurture video-chat rounds: inbound-only copy (user taps call on profile).

INSERT INTO script_template_categories (key, display_name, description, sort_order)
VALUES
    ('nurture_video_round_1', 'Nurture video round 1 (5m)', 'Light invite — user initiates video call.', 70),
    ('nurture_video_round_2', 'Nurture video round 2 (30m)', 'Waiting follow-up — tap call CTA.', 71),
    ('nurture_video_round_3', 'Nurture video round 3 (24h)', 'Emotional recall — tap call tonight.', 72)
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
    -- Round 1 EN
    ('13000000-0000-0000-0000-000000000001','nurture_video_round_1','Round1 EN A','en','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','Still here? Tap call on my profile for a quick video.','[]','["nurture","video_chat","round_1","inbound_call"]','approved'),
    ('13000000-0000-0000-0000-000000000002','nurture_video_round_1','Round1 EN B','en','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','Hey, I''m online — tap video call on my profile whenever you''re ready.','[]','["nurture","video_chat","round_1","variant_b","inbound_call"]','approved'),
    -- Round 1 ZH
    ('13000000-0000-0000-0000-000000000011','nurture_video_round_1','Round1 ZH A','zh','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','我还在呢，点我资料页的视频通话打过来，聊一小会儿？','[]','["nurture","video_chat","round_1","inbound_call"]','approved'),
    ('13000000-0000-0000-0000-000000000012','nurture_video_round_1','Round1 ZH B','zh','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','刚有空上线，想我的话直接点我资料页的视频打过来。','[]','["nurture","video_chat","round_1","variant_b","inbound_call"]','approved'),
    -- Round 1 ES
    ('13000000-0000-0000-0000-000000000021','nurture_video_round_1','Round1 ES A','es','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','Sigo aquí. Toca videollamada en mi perfil si quieres hablar ahora.','[]','["nurture","video_chat","round_1","inbound_call"]','approved'),
    ('13000000-0000-0000-0000-000000000022','nurture_video_round_1','Round1 ES B','es','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','Estoy online. Toca llamada en mi perfil cuando quieras.','[]','["nurture","video_chat","round_1","variant_b","inbound_call"]','approved'),
    -- Round 1 PT
    ('13000000-0000-0000-0000-000000000031','nurture_video_round_1','Round1 PT A','pt','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','Ainda estou aqui. Toca em chamada de vídeo no meu perfil se quiser conversar.','[]','["nurture","video_chat","round_1","inbound_call"]','approved'),
    ('13000000-0000-0000-0000-000000000032','nurture_video_round_1','Round1 PT B','pt','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','Estou online. Toca na chamada do meu perfil quando quiser.','[]','["nurture","video_chat","round_1","variant_b","inbound_call"]','approved'),
    -- Round 2 EN
    ('13000000-0000-0000-0000-000000000101','nurture_video_round_2','Round2 EN A','en','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','I was waiting for you. Tap call on my profile — I''ll pick up.','[]','["nurture","video_chat","round_2","inbound_call"]','approved'),
    ('13000000-0000-0000-0000-000000000102','nurture_video_round_2','Round2 EN B','en','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','You went quiet… I''m still here. Tap video call on my profile when you''re free.','[]','["nurture","video_chat","round_2","variant_b","inbound_call"]','approved'),
    -- Round 2 ZH
    ('13000000-0000-0000-0000-000000000111','nurture_video_round_2','Round2 ZH A','zh','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','我刚刚还在等你，点我资料页的视频通话打过来，我会接。','[]','["nurture","video_chat","round_2","inbound_call"]','approved'),
    ('13000000-0000-0000-0000-000000000112','nurture_video_round_2','Round2 ZH B','zh','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','你怎么不理我了？我还在线，点我资料页的视频打过来就行。','[]','["nurture","video_chat","round_2","variant_b","inbound_call"]','approved'),
    -- Round 2 ES
    ('13000000-0000-0000-0000-000000000121','nurture_video_round_2','Round2 ES A','es','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','Te estaba esperando. Toca videollamada en mi perfil y te contesto.','[]','["nurture","video_chat","round_2","inbound_call"]','approved'),
    ('13000000-0000-0000-0000-000000000122','nurture_video_round_2','Round2 ES B','es','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','¿Sigues ahí? Toca llamada en mi perfil cuando puedas.','[]','["nurture","video_chat","round_2","variant_b","inbound_call"]','approved'),
    -- Round 2 PT
    ('13000000-0000-0000-0000-000000000131','nurture_video_round_2','Round2 PT A','pt','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','Eu estava te esperando. Toca na chamada do meu perfil que eu atendo.','[]','["nurture","video_chat","round_2","inbound_call"]','approved'),
    ('13000000-0000-0000-0000-000000000132','nurture_video_round_2','Round2 PT B','pt','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','Sumiu? Ainda estou aqui. Toca em vídeo no meu perfil quando quiser.','[]','["nurture","video_chat","round_2","variant_b","inbound_call"]','approved'),
    -- Round 3 EN
    ('13000000-0000-0000-0000-000000000201','nurture_video_round_3','Round3 EN A','en','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','I liked talking with you yesterday. Tap call on my profile tonight if you''re free.','[]','["nurture","video_chat","round_3","inbound_call"]','approved'),
    ('13000000-0000-0000-0000-000000000202','nurture_video_round_3','Round3 EN B','en','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','I''m free tonight — tap video call on my profile, or tell me to message you tomorrow.','[]','["nurture","video_chat","round_3","variant_b","inbound_call"]','approved'),
    -- Round 3 ZH
    ('13000000-0000-0000-0000-000000000211','nurture_video_round_3','Round3 ZH A','zh','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','昨天聊得挺开心，今晚有空就点我资料页的视频打过来。','[]','["nurture","video_chat","round_3","inbound_call"]','approved'),
    ('13000000-0000-0000-0000-000000000212','nurture_video_round_3','Round3 ZH B','zh','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','想起了昨天的聊天，今晚方便就点视频打过来，不然我明天再找你？','[]','["nurture","video_chat","round_3","variant_b","inbound_call"]','approved'),
    -- Round 3 ES
    ('13000000-0000-0000-0000-000000000221','nurture_video_round_3','Round3 ES A','es','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','Me gustó hablar contigo ayer. Esta noche toca videollamada en mi perfil si puedes.','[]','["nurture","video_chat","round_3","inbound_call"]','approved'),
    ('13000000-0000-0000-0000-000000000222','nurture_video_round_3','Round3 ES B','es','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','Estoy libre esta noche. Toca llamada en mi perfil o dime y te escribo mañana.','[]','["nurture","video_chat","round_3","variant_b","inbound_call"]','approved'),
    -- Round 3 PT
    ('13000000-0000-0000-0000-000000000231','nurture_video_round_3','Round3 PT A','pt','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','Gostei de falar com você ontem. Hoje à noite toca em chamada no meu perfil se puder.','[]','["nurture","video_chat","round_3","inbound_call"]','approved'),
    ('13000000-0000-0000-0000-000000000232','nurture_video_round_3','Round3 PT B','pt','telegram_real_user','telegram_real_user',NULL,NULL,NULL,'reply','Estou livre hoje à noite. Toca em vídeo no meu perfil ou me avisa para te escrever amanhã.','[]','["nurture","video_chat","round_3","variant_b","inbound_call"]','approved')
ON CONFLICT (id) DO UPDATE
SET category_key = EXCLUDED.category_key,
    title = EXCLUDED.title,
    language = EXCLUDED.language,
    channel = EXCLUDED.channel,
    platform = EXCLUDED.platform,
    content = EXCLUDED.content,
    safety_tags = EXCLUDED.safety_tags,
    status = EXCLUDED.status,
    updated_at = NOW();
