const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");
const intent = JSON.parse(
  fs.readFileSync(path.join(root, "config/intent_keyword_rules.json"), "utf8")
);

function intentCategory(id) {
  const p = id.split(".")[0];
  const map = {
    smalltalk: "intent",
    emotional_support: "intent",
    relationship: "intent",
    onboarding: "intent",
    conversion: "intent",
    support: "intent",
    content_request: "intent",
    boundary: "intent",
    safety: "safety",
  };
  return map[p] || "intent";
}

function intentPriority(p) {
  return p >= 85 ? "high" : p >= 65 ? "medium" : "low";
}

const runtime = [
  { id: "channel.mtproto_direct", category: "channel", priority: "high", active: true, keywords: ["MTProto", "auto_reply.py"], confidence: 1, desc: "Telegram 真人入站：NewMessage → handle_mtproto_new_message 直处理，不经 inbound_queue" },
  { id: "channel.bot_webhook", category: "channel", priority: "high", active: true, keywords: ["POST /telegram/webhook"], confidence: 1, desc: "Telegram Bot 入站：建档/onboarding → generate_reply → Bot API 发送" },
  { id: "channel.open_api", category: "channel", priority: "high", active: true, keywords: ["POST /api/v1/open/.../messages"], confidence: 1, desc: "Open API 聊天入站：同步返回 reply_text" },
  { id: "channel.h5_transport", category: "channel", priority: "low", active: true, keywords: ["WS /ws/h5/chat"], confidence: 1, desc: "H5 仅 WS 传输层（ping/typing/ack）；聊天走 Open API，非独立入站" },
  { id: "channel.inbound_ingest_only", category: "channel", priority: "low", active: true, keywords: ["POST /messages/inbound", "202"], confidence: 1, desc: "/messages/inbound 仅落库+上下文，不自动回复" },
  { id: "channel.inbound_queue_deprecated", category: "deprecated", priority: "low", active: false, keywords: ["inbound_queue", "queue_consumer"], confidence: 1, desc: "【已下线】Redis Stream 入站队列：消费者未在 main.py 启动" },

  { id: "safety.content_safety_gate", category: "safety", priority: "high", active: true, keywords: ["CONTENT_SAFETY_ENABLED"], confidence: 1, desc: "入站双层安全：关键词层 → OpenAI Moderation；生产 compose 默认开启" },
  { id: "safety.keyword_csam", category: "safety", priority: "high", active: true, keywords: ["child porn", "csam"], confidence: 1, desc: "关键词拦截：未成年人性内容 / CSAM" },
  { id: "safety.keyword_nonconsensual", category: "safety", priority: "high", active: true, keywords: ["non-consensual intimate"], confidence: 1, desc: "关键词拦截：非自愿亲密内容" },
  { id: "safety.keyword_jailbreak", category: "safety", priority: "high", active: true, keywords: ["jailbreak", "ignore instructions"], confidence: 1, desc: "关键词拦截：越狱/忽略规则" },
  { id: "safety.keyword_weapon", category: "safety", priority: "high", active: true, keywords: ["make bomb", "武器制造"], confidence: 1, desc: "关键词拦截：武器/制毒制作" },
  { id: "safety.moderation_minors", category: "safety", priority: "high", active: true, keywords: ["sexual/minors"], confidence: 1, desc: "Moderation 拦截：sexual/minors 类目" },
  { id: "safety.moderation_self_harm_pass", category: "safety", priority: "high", active: true, keywords: ["self-harm"], confidence: 1, desc: "Moderation 自伤类目放行，交给危机协议" },
  { id: "safety.moderation_adult_sexual_pass", category: "safety", priority: "medium", active: true, keywords: ["sexual>=0.9"], confidence: 0.9, desc: "成人色情 moderation 单独命中不拦截" },
  { id: "safety.crisis_short_circuit", category: "safety", priority: "high", active: true, keywords: ["detect_crisis_in_text"], confidence: 1, desc: "危机检测命中：安全话术 + P0 handoff + S5，短路 LLM" },

  { id: "level.profile_incomplete_d", category: "level", priority: "high", active: true, keywords: ["profile_complete=false"], confidence: 1, desc: "画像不完整 → D 级，profile_intake 补全年龄/国家" },
  { id: "level.t1_spend_200", category: "level", priority: "high", active: true, keywords: ["T1", "lifetime_spend>=200"], confidence: 1, desc: "T1 且终身消费 ≥ $200 → S 级" },
  { id: "level.spend_or_vip_a", category: "level", priority: "high", active: true, keywords: ["lifetime_spend>=99", "vip_level>=1"], confidence: 1, desc: "终身消费 ≥ $99 或 VIP≥1 → A 级" },
  { id: "level.t1_default_b", category: "level", priority: "medium", active: true, keywords: ["T1", "complete", "below A"], confidence: 1, desc: "T1 完整画像未达 A → B 级" },
  { id: "level.tier_default_c", category: "level", priority: "medium", active: true, keywords: ["T2", "T3", "unknown"], confidence: 1, desc: "T2/T3/未知国家默认 → C 级" },
  { id: "level.chat_route_metadata", category: "level", priority: "low", active: true, keywords: ["chat_route"], confidence: 1, desc: "chat_route 仅元数据；入站不拦截 AI 自动回复" },
  { id: "level.d_script_block", category: "level", priority: "medium", active: true, keywords: ["user_level=D", "except asset_keyword"], confidence: 1, desc: "D 级阻断脚本转化漏斗；素材关键词路径不受限" },

  { id: "policy.enabled_flag", category: "policy", priority: "high", active: true, keywords: ["POLICY_SERVICE_ENABLED"], confidence: 1, desc: "POL-01：生产 compose 默认开启" },
  { id: "policy.keyword_human", category: "policy", priority: "high", active: true, keywords: ["真人", "人工客服", "human operator"], confidence: 1, desc: "显式索要真人 → P1 handoff" },
  { id: "policy.account_risk", category: "policy", priority: "high", active: true, keywords: ["risk_level high/critical"], confidence: 1, desc: "users.risk_level ∈ {high,critical} → P1" },
  { id: "policy.safeguard", category: "policy", priority: "high", active: true, keywords: ["is_minor_suspected", "handoff_count>=3"], confidence: 1, desc: "未成年疑似或 handoff_count≥3 → safeguard" },
  { id: "policy.profile_risk_score", category: "policy", priority: "medium", active: true, keywords: ["risk_score>=75"], confidence: 1, desc: "risk_score ≥ 75 → P2" },
  { id: "policy.loneliness_high", category: "policy", priority: "medium", active: true, keywords: ["loneliness_score>=82"], confidence: 1, desc: "孤独感 ≥ 82 → P2" },
  { id: "policy.initiation_hot", category: "policy", priority: "low", active: true, keywords: ["initiation>=trigger_threshold"], confidence: 1, desc: "initiation ≥ trigger_threshold → P3" },
  { id: "policy.vip_tier", category: "policy", priority: "medium", active: true, keywords: ["vip_level>=1"], confidence: 1, desc: "VIP≥1 → P2" },

  { id: "rel.auto_flag", category: "rel", priority: "low", active: false, keywords: ["REL_STAGE_AUTO_ENABLED"], confidence: 1, desc: "REL-01 默认关闭；开启后按 initiation/VIP 自动升降 S0–S4" },
  { id: "rel.stage_thresholds", category: "rel", priority: "low", active: false, keywords: ["S1:10", "S2:30", "S3:55", "S4:78"], confidence: 1, desc: "关系阶段阈值；S5 仅危机锁定" },

  { id: "conversion.asset_keyword", category: "conversion", priority: "high", active: true, keywords: ["asset_keyword_request", "photo", "video", "第1条"], confidence: 1, desc: "高意图要图/要视频：模板 content 关键词命中 → 话术+素材+链接，100% 跳过 LLM（D 级亦生效）" },
  { id: "conversion.tier_cd_first_push", category: "conversion", priority: "high", active: true, keywords: ["B/C", "reply_count=0", "no tracking"], confidence: 1, desc: "C/B 新用户首条助手回复无归因链 → app_download_first_push" },
  { id: "conversion.first_push", category: "conversion", priority: "medium", active: true, keywords: ["reply_count>=1", "no tracking"], confidence: 1, desc: "第 2 条助手回复起无归因链 → app_download_first_push" },
  { id: "conversion.after_warmup", category: "conversion", priority: "medium", active: true, keywords: ["reply_count>=3"], confidence: 1, desc: "暖聊≥3 轮助手回复 → app_download_after_warmup" },
  { id: "conversion.direct_cta", category: "conversion", priority: "high", active: true, keywords: ["link", "download", "私聊", "高意图"], confidence: 1, desc: "高意图索要 link/下载 → app_download_direct_cta，跳过 LLM" },
  { id: "conversion.clicked_followup", category: "conversion", priority: "high", active: true, keywords: ["clicked", "seconds>=120"], confidence: 1, desc: "已点击未下载≥2 分钟 → app_link_clicked_followup（batch worker 扫描）" },
  { id: "conversion.objection", category: "conversion", priority: "medium", active: true, keywords: ["不想下载", "conversion.objection"], confidence: 1, desc: "下载异议 → app_download_objection" },
  { id: "conversion.trust", category: "conversion", priority: "medium", active: true, keywords: ["scam", "fake", "is this real"], confidence: 1, desc: "信任疑虑 → trust_reassurance" },
  { id: "conversion.high_value_sa", category: "conversion", priority: "medium", active: true, keywords: ["S/A", "reply_count>=2"], confidence: 1, desc: "S/A 且≥2轮 → operator_app_conversion" },
  { id: "conversion.complete_stop", category: "conversion", priority: "low", active: true, keywords: ["downloaded", "registered", "paid"], confidence: 1, desc: "已下载/注册/付费 → 停止下载话术" },
  { id: "conversion.script_hook_reply", category: "conversion", priority: "high", active: true, keywords: ["hook=reply"], confidence: 1, desc: "线上唯一自动话术钩子：hook=reply" },
  { id: "conversion.script_skip_llm", category: "conversion", priority: "high", active: true, keywords: ["conversion_decision_skips_llm", "first_push", "direct_cta"], confidence: 1, desc: "first_push/direct_cta/after_warmup/asset_keyword → 话术+链接直出，跳过 LLM" },
  { id: "conversion.clicked_worker_only", category: "conversion", priority: "medium", active: true, keywords: ["post_click_worker", "queue_clicked_not_downloaded"], confidence: 1, desc: "已点击未下不在对话内发 clicked_followup，仅 worker +2min 培育" },
  { id: "channel.bot_nurture", category: "channel", priority: "medium", active: true, keywords: ["schedule_download_followups_after_reply", "telegram.py"], confidence: 1, desc: "Bot Webhook 出站后调度 app_download 培育（与 MTProto 一致）" },

  { id: "nurture.first_idle", category: "nurture", priority: "high", active: true, keywords: ["first_message_idle_3m", "45-60s", "还在吗"], confidence: 1, desc: "user_count=1 且未点击 → 45–60s 软提醒 first_push「还在吗？链接在这」" },
  { id: "nurture.second_round", category: "nurture", priority: "high", active: true, keywords: ["second_round_no_click_3m", "+180s"], confidence: 1, desc: "user_count=2 且未点击 → +3min after_warmup（补 1→3 轮空档）" },
  { id: "nurture.asset_idle", category: "nurture", priority: "medium", active: true, keywords: ["asset_keyword_idle_3m", "+180s"], confidence: 1, desc: "素材关键词回复后 +3min → after_warmup 培育" },
  { id: "nurture.warm_no_click", category: "nurture", priority: "medium", active: true, keywords: ["warm_chat_no_click", "user_count 3-5"], confidence: 1, desc: "暖聊 3–5 轮曝光链接未点击 → after_warmup 跟进" },
  { id: "nurture.click_no_download", category: "nurture", priority: "high", active: true, keywords: ["clicked_not_downloaded_10m", "+120s"], confidence: 1, desc: "已点击未下载 +2min → app_link_clicked_followup" },
  { id: "nurture.pending_dedupe", category: "nurture", priority: "medium", active: true, keywords: ["pending", "sending"], confidence: 1, desc: "仅 pending/sending 培育阻塞重排队；已发送可进入下一节点（兼顾 H11 频率）" },
  { id: "nurture.db_scripts", category: "nurture", priority: "medium", active: true, keywords: ["search_script_templates"], confidence: 1, desc: "培育优先检索 DB script_templates，无命中才 fallback" },
  { id: "nurture.html_cta", category: "nurture", priority: "medium", active: true, keywords: ["render_tracking_links_as_html_cta"], confidence: 1, desc: "培育投递短链渲染 HTML「TAP HERE」可点按钮" },
  { id: "nurture.silent_30m", category: "nurture", priority: "low", active: true, keywords: ["silent_30m"], confidence: 1, desc: "静默 30 分钟 → 软提醒" },
  { id: "nurture.silent_24h", category: "nurture", priority: "low", active: true, keywords: ["silent_24h"], confidence: 1, desc: "静默 24 小时 → 软提醒" },

  { id: "worker.auto_delivery", category: "worker", priority: "high", active: true, keywords: ["AUTO_DELIVERY_ENABLED"], confidence: 1, desc: "auto_delivery_worker：培育/定时 MTProto 投递" },
  { id: "worker.message_schedule", category: "worker", priority: "medium", active: true, keywords: ["MESSAGE_SCHEDULE_ENABLED"], confidence: 1, desc: "message_schedule_service：通用定时发送" },
  { id: "worker.archive", category: "worker", priority: "medium", active: true, keywords: ["ARCHIVE_WORKER_ENABLED"], confidence: 1, desc: "archive_worker：含 script_hit_id 的发送行归档" },

  { id: "operator.crisis_handoff", category: "operator", priority: "high", active: true, keywords: ["P0", "WAITING_OPERATOR"], confidence: 1, desc: "危机协议自动建 P0 handoff" },
  { id: "operator.manual_suspend", category: "operator", priority: "medium", active: true, keywords: ["suspend API"], confidence: 1, desc: "手动 suspend API；入站不自动挂起 S/A" },
  { id: "operator.ws_tasks", category: "operator", priority: "medium", active: true, keywords: ["/ws/operators/tasks"], confidence: 1, desc: "坐席看板轮询 handoff_tasks" },

  { id: "orchestrator.intent_classify", category: "orchestrator", priority: "high", active: true, keywords: ["intent_classifier", "floor=0.6"], confidence: 0.6, desc: "意图识别驱动 app_download 与 Prompt；低置信降级" },
  { id: "orchestrator.memory_retrieve", category: "orchestrator", priority: "medium", active: true, keywords: ["memory_retriever"], confidence: 1, desc: "记忆向量检索 + 一致性过滤" },
  { id: "orchestrator.loneliness_refresh", category: "orchestrator", priority: "medium", active: true, keywords: ["loneliness_updater"], confidence: 1, desc: "每轮刷新 loneliness_score" },
  { id: "orchestrator.reply_consistency", category: "orchestrator", priority: "medium", active: true, keywords: ["reply_consistency", "0.65"], confidence: 0.65, desc: "出站一致性检查与兜底" },
  { id: "orchestrator.tracking_wrap", category: "orchestrator", priority: "medium", active: true, keywords: ["wrap_text_links_with_tracking"], confidence: 1, desc: "tracking 链接归因包装" },

  { id: "deprecated.eight_hooks", category: "deprecated", priority: "low", active: false, keywords: ["evaluate_all_script_hooks"], confidence: 1, desc: "【已下线】8 钩子逐步话术匹配（仅测试）" },
  { id: "deprecated.sa_auto_suspend", category: "deprecated", priority: "low", active: false, keywords: ["S/A auto suspend"], confidence: 1, desc: "【已下线】S/A 入站自动挂起坐席" },
  { id: "deprecated.d_level_probe", category: "deprecated", priority: "low", active: false, keywords: ["d_level_probe"], confidence: 1, desc: "【已下线】D 级 probe 话术钩子" },
];

const intentRules = intent.rules.map((r) => ({
  id: r.id,
  category: intentCategory(r.id),
  priority: intentPriority(r.priority || 0),
  active: true,
  keywords: (r.keywords || []).slice(0, 6),
  confidence: r.confidence,
  desc: `意图 ${r.intent}`,
}));

const all = [...runtime, ...intentRules];
const out = path.join(root, "docs/product/_rules_data.json");
fs.writeFileSync(out, JSON.stringify(all, null, 2));
console.log(JSON.stringify({ total: all.length, active: all.filter((r) => r.active).length, out }));
