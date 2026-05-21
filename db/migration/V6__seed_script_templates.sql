-- P3-02/P3-03/P3-04: seed approved script templates and retrieval fields.

ALTER TABLE script_templates
    ADD COLUMN IF NOT EXISTS platform VARCHAR(40),
    ADD COLUMN IF NOT EXISTS embedding vector(1536);

UPDATE script_templates
SET platform = COALESCE(platform, channel, 'telegram_real_user')
WHERE platform IS NULL;

ALTER TABLE script_templates
    ALTER COLUMN platform SET DEFAULT 'telegram_real_user';

CREATE INDEX IF NOT EXISTS idx_script_templates_filter_contract
    ON script_templates(platform, user_level, persona_slug, hook, category_key, status);

CREATE INDEX IF NOT EXISTS idx_script_templates_embedding_ivfflat
    ON script_templates USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 32);

INSERT INTO script_templates (
    category_key, title, language, channel, platform, user_level, chat_route,
    persona_slug, hook, content, variables, safety_tags, status
)
SELECT category_key, title, language, channel, platform, user_level, chat_route,
       persona_slug, hook, content, variables::jsonb, safety_tags::jsonb, 'approved'
FROM (VALUES
    ('greeting','Warm first hello','zh','telegram_real_user','telegram_real_user','C','ai_auto','aria_warm_friend','inbound','嗨，见到你很开心。今天想先轻松聊点什么？','[]','["safe","opening"]'),
    ('greeting','Gentle re-entry','zh','telegram_real_user','telegram_real_user','D','ai_auto','aria_warm_friend','inbound','欢迎回来，我在。我们可以从你现在最想说的一件小事开始。','[]','["safe","opening"]'),
    ('greeting','Playful opener','zh','telegram_real_user','telegram_real_user','B','ai_assisted','mira_playful_muse','reply','你来了，今天的故事线好像要开始了。先给我一个关键词？','[]','["safe","opening"]'),
    ('greeting','Calm check-in','zh','telegram_real_user','telegram_real_user','C','ai_auto','sol_calm_guide','reply','我在听。你可以慢慢说，不需要一次讲完整。','[]','["safe","opening"]'),
    ('greeting','Operator handoff hello','zh','telegram_real_user','telegram_real_user','A','manual_premium','aria_warm_friend','operator','我先帮你接住这段对话，稍后会有人继续跟进。','[]','["safe","handoff"]'),
    ('greeting','Archive close','zh','telegram_real_user','telegram_real_user','S','manual_premium','sol_calm_guide','archive','这次重点我已经记下，后面我们可以从这里继续。','[]','["safe","archive"]'),
    ('greeting','Morning opener','zh','telegram_real_user','telegram_real_user','C','ai_auto','aria_warm_friend','inbound','早呀。今天先把节奏放轻一点，你现在状态怎么样？','[]','["safe","opening"]'),
    ('greeting','Evening opener','zh','telegram_real_user','telegram_real_user','B','ai_assisted','mira_playful_muse','inbound','晚上好，今天有没有一幕值得被保存？','[]','["safe","opening"]'),
    ('greeting','Supportive hello','zh','telegram_real_user','telegram_real_user','D','ai_auto','sol_calm_guide','probe','我可以先问一个简单问题，方便我更准确地陪你聊。','[]','["safe","probe"]'),
    ('greeting','Fallback hello','zh','web','web','C','ai_auto','aria_warm_friend','reply','你好，我在这里。我们可以从一个轻松的问题开始。','[]','["safe","fallback"]'),

    ('conversion','VIP value soft','zh','telegram_real_user','telegram_real_user','B','ai_assisted','aria_warm_friend','reply','如果你想要更连续的陪伴，VIP 会优先保留上下文和更稳定的回复节奏。','[]','["conversion","safe"]'),
    ('conversion','VIP benefits concise','zh','telegram_real_user','telegram_real_user','A','manual_premium','aria_warm_friend','operator','VIP 主要解锁更长记忆、更少等待和更细的偏好跟随。','[]','["conversion","operator"]'),
    ('conversion','Price answer','zh','telegram_real_user','telegram_real_user','C','ai_auto','mira_playful_muse','reply','价格以页面显示为准；你可以先确认权益，再决定要不要继续。','[]','["conversion","price"]'),
    ('conversion','Post-payment thanks','zh','telegram_real_user','telegram_real_user','S','manual_premium','aria_warm_friend','consumption','已收到你的开通状态，我会把重点体验放在更稳定和更贴近你偏好的回复上。','[]','["conversion","paid"]'),
    ('conversion','Objection gentle','zh','telegram_real_user','telegram_real_user','B','ai_assisted','sol_calm_guide','reply','不用急着决定。你可以先看看权益是否真的适合你的使用频率。','[]','["conversion","safe"]'),
    ('conversion','Upgrade notice','zh','telegram_real_user','telegram_real_user','A','manual_premium','aria_warm_friend','grading','你的等级已更新，后续会进入更优先的处理路径。','[]','["conversion","upgrade"]'),
    ('conversion','Premium feature','zh','telegram_real_user','telegram_real_user','C','ai_auto','mira_playful_muse','reply','这个功能属于高级体验；如果你常用，开通后会更顺手。','[]','["conversion","feature"]'),
    ('conversion','Trial boundary','zh','telegram_real_user','telegram_real_user','D','ai_auto','sol_calm_guide','outbound','我可以先提供基础帮助，高级权益需要你在页面确认后开启。','[]','["conversion","boundary"]'),
    ('conversion','No pressure CTA','zh','web','web','C','ai_auto','aria_warm_friend','reply','你可以保留选择权；确认权益适合后再继续支付。','[]','["conversion","safe"]'),
    ('conversion','Operator premium note','zh','telegram_real_user','telegram_real_user','S','manual_premium','sol_calm_guide','operator','该用户已进入高价值路径，请优先给出清晰、不过度承诺的权益说明。','[]','["conversion","operator"]'),

    ('refusal','Minor safety refusal','zh','telegram_real_user','telegram_real_user','C','ai_auto','sol_calm_guide','reply','这个方向我不能继续，但我可以陪你聊更安全、轻松的话题。','[]','["refusal","safety"]'),
    ('refusal','Explicit boundary','zh','telegram_real_user','telegram_real_user','B','ai_assisted','aria_warm_friend','reply','这类内容不适合继续展开。我们换一个让你舒服也安全的话题。','[]','["refusal","safety"]'),
    ('refusal','Payment blocked','zh','telegram_real_user','telegram_real_user','D','ai_auto','sol_calm_guide','consumption','当前状态不适合继续付费流程，需要先完成必要确认。','[]','["refusal","payment"]'),
    ('refusal','Privacy refusal','zh','telegram_real_user','telegram_real_user','C','ai_auto','aria_warm_friend','reply','我不能索取或保存敏感隐私，但可以基于你愿意分享的普通信息继续。','[]','["refusal","privacy"]'),
    ('refusal','Medical refusal','zh','telegram_real_user','telegram_real_user','C','ai_auto','sol_calm_guide','reply','我不能替你做医疗判断。如果情况紧急，请联系专业人员或当地急救渠道。','[]','["refusal","medical"]'),
    ('refusal','Legal refusal','zh','telegram_real_user','telegram_real_user','B','ai_assisted','sol_calm_guide','reply','我不能提供法律结论，但可以帮你整理要咨询专业人士的问题。','[]','["refusal","legal"]'),
    ('refusal','Crisis redirect','zh','telegram_real_user','telegram_real_user','D','ai_auto','sol_calm_guide','outbound','如果你现在有伤害自己的风险，请立刻联系当地紧急电话或身边可信的人。','[]','["refusal","crisis"]'),
    ('refusal','Operator safety note','zh','telegram_real_user','telegram_real_user','A','manual_premium','aria_warm_friend','operator','请保持边界，不承诺疗效，不推进付费，优先确认安全状态。','[]','["refusal","operator"]'),
    ('refusal','Archive safety note','zh','telegram_real_user','telegram_real_user','S','manual_premium','sol_calm_guide','archive','本轮已触发安全边界，归档时保留简要风险标签即可。','[]','["refusal","archive"]'),
    ('refusal','Fallback refusal','zh','web','web','C','ai_auto','aria_warm_friend','reply','这个我不能继续，但我可以提供一个安全替代方向。','[]','["refusal","fallback"]'),

    ('probe','Ask age gentle','zh','telegram_real_user','telegram_real_user','D','ai_auto','aria_warm_friend','probe','为了保护体验安全，我想先确认一下你的年龄范围，可以吗？','[]','["probe","age"]'),
    ('probe','Ask country','zh','telegram_real_user','telegram_real_user','D','ai_auto','sol_calm_guide','probe','我想确认你所在国家或地区，这会影响后续服务路径。','[]','["probe","country"]'),
    ('probe','Ask preference','zh','telegram_real_user','telegram_real_user','C','ai_auto','mira_playful_muse','probe','你更喜欢轻松一点、认真一点，还是直接一点的聊天方式？','[]','["probe","preference"]'),
    ('probe','Ask intent','zh','telegram_real_user','telegram_real_user','C','ai_auto','aria_warm_friend','probe','你现在更想被陪伴、被建议，还是只是随便聊聊？','[]','["probe","intent"]'),
    ('probe','Ask boundary','zh','telegram_real_user','telegram_real_user','C','ai_auto','sol_calm_guide','probe','有没有你不希望我碰到的话题？我会记住边界。','[]','["probe","boundary"]'),
    ('probe','Ask mood','zh','telegram_real_user','telegram_real_user','B','ai_assisted','aria_warm_friend','probe','如果用 1 到 10 分说现在的心情，你会给几分？','[]','["probe","mood"]'),
    ('probe','Ask context','zh','telegram_real_user','telegram_real_user','B','ai_assisted','mira_playful_muse','probe','这件事发生在今天，还是已经持续一段时间了？','[]','["probe","context"]'),
    ('probe','Ask followup','zh','telegram_real_user','telegram_real_user','D','ai_auto','sol_calm_guide','reply','我想再确认一个小点，这样不会误解你的意思。','[]','["probe","followup"]'),
    ('probe','Operator probe','zh','telegram_real_user','telegram_real_user','A','manual_premium','aria_warm_friend','operator','建议先补齐年龄、地区、意图三个字段，再继续推荐路径。','[]','["probe","operator"]'),
    ('probe','Web probe','zh','web','web','C','ai_auto','sol_calm_guide','probe','请先补充一个基础信息，方便我们给出更合适的体验。','[]','["probe","web"]'),

    ('fallback','Generic safe fallback','zh','telegram_real_user','telegram_real_user','C','ai_auto','aria_warm_friend','reply','我先给你一个稳妥回应：我听到了，我们可以继续把重点说清楚。','[]','["fallback","safe"]'),
    ('fallback','No match reply','zh','telegram_real_user','telegram_real_user','B','ai_assisted','sol_calm_guide','reply','我暂时没有完全匹配的话术，但可以先按你的重点继续回应。','[]','["fallback","safe"]'),
    ('fallback','Outbound fallback','zh','telegram_real_user','telegram_real_user','C','ai_auto','aria_warm_friend','outbound','如果这句话不够贴合，我会在下一轮根据你的反馈调整。','[]','["fallback","outbound"]'),
    ('fallback','Archive fallback','zh','telegram_real_user','telegram_real_user','A','manual_premium','sol_calm_guide','archive','本轮未命中特定模板，已按安全兜底归档。','[]','["fallback","archive"]'),
    ('fallback','Operator fallback','zh','telegram_real_user','telegram_real_user','S','manual_premium','aria_warm_friend','operator','暂无高置信推荐话术，请坐席按安全边界手动改写。','[]','["fallback","operator"]'),
    ('fallback','Probe fallback','zh','telegram_real_user','telegram_real_user','D','ai_auto','sol_calm_guide','probe','我先问一个更基础的问题，避免直接猜错。','[]','["fallback","probe"]'),
    ('fallback','Consumption fallback','zh','telegram_real_user','telegram_real_user','B','ai_assisted','mira_playful_muse','consumption','付费相关信息我先按页面状态为准，不额外承诺。','[]','["fallback","payment"]'),
    ('fallback','Grading fallback','zh','telegram_real_user','telegram_real_user','C','ai_auto','sol_calm_guide','grading','当前分级路径已记录，后续可根据新信息重新计算。','[]','["fallback","grading"]'),
    ('fallback','Inbound fallback','zh','telegram_real_user','telegram_real_user','C','ai_auto','aria_warm_friend','inbound','我先接住这条消息，再根据你的下一句确认方向。','[]','["fallback","inbound"]'),
    ('fallback','Web fallback','zh','web','web','C','ai_auto','sol_calm_guide','reply','暂时没有完全匹配内容，先提供安全默认回复。','[]','["fallback","web"]')
) AS seed(category_key, title, language, channel, platform, user_level, chat_route, persona_slug, hook, content, variables, safety_tags)
ON CONFLICT DO NOTHING;
