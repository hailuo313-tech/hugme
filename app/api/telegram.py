"""
D1-1 + D1-3 + D2-2 + D2-3: Telegram Webhook 接入 + Onboarding + LLM Orchestrator

消息路由逻辑：
  新用户（onboarding_step == 0）       → 触发 Onboarding Step 1
  Onboarding 进行中（step 1-5）        → 提交答案，发下一问题
  Onboarding 完成（step >= 6）         → 走 LLM Orchestrator 生成回复（D2-2）

幂等：Redis SET NX tg-{update_id}
Redis 短期上下文：ctx:{conv_id} 保留最近 20 条
"""
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from core.database import get_db
from core.config import settings
from loguru import logger
import uuid, time, json
import httpx
import redis.asyncio as aioredis

# Onboarding 工具（复用 onboarding.py 的逻辑）
from api.onboarding import (
    _get_or_create_user,
    _get_profile_prefs,
    _assign_character,
    _load_onboarding_profile,
    _build_next_question,
    _build_completion_message,
    _detect_onboarding_language,
    _ensure_aria_exists,
    _fallback_nickname,
    _normalize_onboarding_language,
    ONBOARDING_STEPS,
    CHAT_STYLE_MAP,
    DEFAULT_CHARACTER_ID,
)
from services.llm_orchestrator import generate_reply, LLMOrchestratorError
from services.app_download_conversion import get_last_app_download_decision
from services.link_attribution import render_tracking_links_as_html_cta, wrap_text_links_with_tracking
from services.script_asset_delivery import send_telegram_bot_asset
from services.memory_writer import maybe_write_memory
from services.age_extraction import maybe_extract_and_write_age
from services.content_safety import evaluate_inbound_content_safety
from services.emotion_lexicon import detect_language_from_text, normalize_language
from services.minor_protection import evaluate_inbound_minor_protection
from services.user_level_service import user_level_service
from services.profile_intake import (
    country_from_recent_user_messages,
    country_from_locale,
    country_from_text_language,
    extract_age_from_text,
    normalize_country_code,
    read_profile_completeness,
    write_age,
    write_country_code,
)
from services.reply_consistency import (
    evaluate_reply_consistency,
    load_reply_consistency_context,
)
import asyncio
import re

router = APIRouter()
INBOUND_TYPING_START_DELAY_SECONDS = 5.0
PROFILE_COUNTRY_QUESTION = (
    "Before we continue, which country are you in? You can reply with a country name or code, like US, Canada, Japan, or Germany."
)
PROFILE_COUNTRY_RETRY = (
    "I could not recognize that country. Please reply with your country name or a two-letter code, like US, GB, JP, or SG."
)
PROFILE_AGE_QUESTION = "Thanks. How old are you?"
PROFILE_AGE_RETRY = "Please reply with your age as a number, for example 24."

_PROFILE_COPY = {
    "es": {
        "country_question": "Antes de seguir, ¿en qué país estás? Puedes responder con el país o el código, como US, Canada, Japan o Germany.",
        "country_retry": "No pude reconocer ese país. Responde con el nombre de tu país o un código de dos letras, como US, GB, JP o SG.",
        "age_question": "Gracias. ¿Cuántos años tienes?",
        "age_retry": "Responde con tu edad en número, por ejemplo 24.",
    },
    "pt": {
        "country_question": "Antes de continuar, em que país você está? Pode responder com o país ou o código, como US, Canada, Japan ou Germany.",
        "country_retry": "Não consegui reconhecer esse país. Responda com o nome do país ou um código de duas letras, como US, GB, JP ou SG.",
        "age_question": "Obrigado. Quantos anos você tem?",
        "age_retry": "Responda com sua idade em número, por exemplo 24.",
    },
    "ja": {
        "country_question": "続ける前に、どの国にいますか？US、Canada、Japan、Germany のように国名かコードで答えてください。",
        "country_retry": "その国を認識できませんでした。US、GB、JP、SG のように国名か2文字コードで答えてください。",
        "age_question": "ありがとう。何歳ですか？",
        "age_retry": "年齢を数字で答えてください。例: 24",
    },
    "ko": {
        "country_question": "계속하기 전에 어느 나라에 있나요? US, Canada, Japan, Germany처럼 나라 이름이나 코드로 답해 주세요.",
        "country_retry": "그 국가는 인식하지 못했어요. US, GB, JP, SG처럼 국가명이나 두 글자 코드로 답해 주세요.",
        "age_question": "고마워요. 몇 살인가요?",
        "age_retry": "나이를 숫자로 답해 주세요. 예: 24",
    },
}


def _profile_copy(kind: str, text_content: str, fallback: str) -> str:
    language = normalize_language(
        detect_language_from_text(text_content or "", default="en"),
        default="en",
    )
    return _PROFILE_COPY.get(language, {}).get(kind, fallback)

# ── Redis 单例 ────────────────────────────────────────
_redis_client = None

async def get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL, encoding="utf-8", decode_responses=True
        )
    return _redis_client

# ── 常量 ──────────────────────────────────────────────
CONTEXT_MAX_MESSAGES = 20
CONTEXT_TTL_SECONDS  = 86400 * 3
IDEM_TTL_SECONDS     = 86400


# ── 工具函数 ──────────────────────────────────────────

def _make_trace_id() -> str:
    return str(uuid.uuid4()).replace("-", "")[:16]

def _idem_key(update_id) -> str:
    return f"tg-{update_id}"

async def _push_context(redis, conv_id: str, role: str, content: str, msg_id: str):
    key = f"ctx:{conv_id}"
    entry = json.dumps({
        "role": role, "content": content,
        "msg_id": msg_id, "ts": int(time.time()),
    }, ensure_ascii=False)
    pipe = redis.pipeline()
    pipe.rpush(key, entry)
    pipe.ltrim(key, -CONTEXT_MAX_MESSAGES, -1)
    pipe.expire(key, CONTEXT_TTL_SECONDS)
    await pipe.execute()

def _human_typing_delay(text_content: str) -> float:
    """根据回复字数返回模拟真人打字延迟（秒）。
    ≤10字 → 4s，11-30字 → 7s，31-50字 → 11s，51-100字 → 18s，>100字 → 18s
    """
    n = len(text_content)
    if n <= 10:
        return 4.0
    if n <= 30:
        return 7.0
    if n <= 50:
        return 11.0
    return 18.0


async def _send_tg(chat_id: int, text_content: str, trace_id: str, typing_delay: bool = False) -> int | None:
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if typing_delay:
                delay = _human_typing_delay(text_content)
                await asyncio.sleep(INBOUND_TYPING_START_DELAY_SECONDS)
                # 发送"正在输入…"状态
                try:
                    await client.post(
                        f"https://api.telegram.org/bot{token}/sendChatAction",
                        json={"chat_id": chat_id, "action": "typing"},
                    )
                except Exception:
                    pass
                await asyncio.sleep(delay)
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text_content, "parse_mode": "HTML"},
            )
            result = resp.json()
            if result.get("ok"):
                mid = result["result"]["message_id"]
                logger.info(f"[{trace_id}] tg.send.ok sent_msg_id={mid}")
                return mid
            else:
                logger.warning(f"[{trace_id}] tg.send.fail resp={result}")
    except Exception as e:
        logger.warning(f"[{trace_id}] tg.send.error err={e}")
    return None

async def _persist_message(
    db: AsyncSession,
    conv_id: str,
    sender_type: str,
    sender_id: str,
    content: str,
    safety_result: dict | None = None,
    consistency_score: float | None = None,
    message_id: str | None = None,
) -> str:
    msg_id = message_id or str(uuid.uuid4())
    if safety_result is not None:
        await db.execute(
            text(
                "INSERT INTO messages "
                "(id,conversation_id,sender_type,sender_id,content,content_type,"
                " safety_result,consistency_score) "
                "VALUES (:id,:cid,:st,:sid,:ct,'text', CAST(:sr AS jsonb), :cs)"
            ),
            {
                "id": msg_id,
                "cid": conv_id,
                "st": sender_type,
                "sid": sender_id,
                "ct": content,
                "sr": json.dumps(safety_result, ensure_ascii=False),
                "cs": consistency_score,
            },
        )
    else:
        await db.execute(
            text(
                "INSERT INTO messages "
                "(id,conversation_id,sender_type,sender_id,content,content_type,"
                " consistency_score) "
                "VALUES (:id,:cid,:st,:sid,:ct,'text', :cs)"
            ),
            {
                "id": msg_id,
                "cid": conv_id,
                "st": sender_type,
                "sid": sender_id,
                "ct": content,
                "cs": consistency_score,
            },
        )
    await db.execute(
        text("UPDATE conversations SET last_message_at=NOW(), updated_at=NOW() WHERE id=:id"),
        {"id": conv_id},
    )
    await db.commit()
    return msg_id


# Bot command handling. Commands are handled before onboarding/LLM and do not
# mutate user state.
HELP_TEXT = (
    "🫂 <b>ERIS 命令列表</b>\n\n"
    "/start   — 开始 Onboarding，认识 Aria\n"
    "/help    — 查看所有命令\n"
    "/reset   — 删除我的全部数据\n"
    "/privacy — 隐私说明\n\n"
    "也可以直接打字和 Aria 聊天 ✨"
)

PRIVACY_TEXT = (
    "🔒 <b>隐私说明</b>\n\n"
    "• 你的对话内容加密存储，仅用于为你提供陪伴服务。\n"
    "• 我们不会将你的数据用于广告、营销或出售给第三方。\n"
    "• 你可以随时通过 /reset 请求删除全部个人数据。\n"
    "• 匿名化后的统计数据可能用于改进服务质量。\n\n"
    "如有疑问，请联系：hello@hugme2.com"
)

RESET_PROMPT_TEXT = (
    "⚠️ <b>确认删除</b>\n\n"
    "此操作将永久删除你的全部数据，包括对话记录、记忆和个人偏好。\n\n"
    "如需继续，请回复：<code>CONFIRM-DELETE</code>\n\n"
    "（此功能尚在开发中，回复后暂不会执行实际删除。）"
)


async def _handle_command(command: str) -> str | None:
    """Return a bot command response, or None to fall through to chat flow."""
    cmd = (command or "").split()[0].lower().split("@")[0]
    if cmd == "/help":
        return HELP_TEXT
    if cmd == "/privacy":
        return PRIVACY_TEXT
    if cmd == "/reset":
        return RESET_PROMPT_TEXT
    if cmd == "/start":
        return None
    return None


async def _persist_technical_country_hint(
    db: AsyncSession,
    *,
    user_id: str,
    tg_user: dict,
    log,
) -> None:
    code = country_from_locale(tg_user.get("language_code"))
    if not code:
        return
    completeness = await read_profile_completeness(db, user_id=user_id)
    if completeness.country_code:
        return
    await write_country_code(
        db,
        user_id=user_id,
        country_code=code,
        source="telegram_language_code",
    )
    await db.commit()
    log.bind(country_code=code).info("tg.profile.country_detected")


async def _classify_user_level(
    db: AsyncSession,
    *,
    user_id: str,
    external_id: str,
    log,
) -> None:
    result = await user_level_service.calculate_and_persist_user_level(
        db,
        user_id=user_id,
        external_user_id=external_id,
    )
    log.bind(
        user_level=result["level"],
        chat_route=result["chat_route"],
        level_reason=result["reason"],
    ).info("tg.profile.level_classified")


async def _handle_required_profile_intake(
    db: AsyncSession,
    *,
    user_id: str,
    chat_id: int,
    text_content: str,
    trace_id: str,
    onboarding_done: bool,
    language: str,
    external_id: str,
    log,
) -> str | None:
    prefs = await _get_profile_prefs(db, user_id)
    pending = str(prefs.get("profile_intake_pending") or "").strip()
    completeness = await read_profile_completeness(db, user_id=user_id)

    if pending == "country":
        country_code = normalize_country_code(text_content)
        if not country_code:
            country_code = await country_from_recent_user_messages(
                db,
                user_id=user_id,
            )
        if not country_code:
            retry = _profile_copy("country_retry", text_content, PROFILE_COUNTRY_RETRY)
            await _send_tg(chat_id, retry, trace_id, typing_delay=True)
            return retry
        await write_country_code(
            db,
            user_id=user_id,
            country_code=country_code,
            source="chat_answer",
        )
        prefs["profile_intake_pending"] = "age"
        await db.execute(
            text("UPDATE user_profiles SET preferences=:v, updated_at=NOW() WHERE user_id=:uid"),
            {"v": json.dumps(prefs, ensure_ascii=False), "uid": user_id},
        )
        await db.commit()
        await _classify_user_level(
            db,
            user_id=user_id,
            external_id=external_id,
            log=log,
        )
        await db.commit()
        age_question = _profile_copy("age_question", text_content, PROFILE_AGE_QUESTION)
        await _send_tg(chat_id, age_question, trace_id, typing_delay=True)
        log.bind(country_code=country_code).info("tg.profile.country_collected")
        return age_question

    if pending == "age":
        age = extract_age_from_text(text_content)
        if age is None:
            retry = _profile_copy("age_retry", text_content, PROFILE_AGE_RETRY)
            await _send_tg(chat_id, retry, trace_id, typing_delay=True)
            return retry
        await write_age(db, user_id=user_id, age=age, source="chat_answer")
        prefs.pop("profile_intake_pending", None)
        await db.execute(
            text("UPDATE user_profiles SET preferences=:v, updated_at=NOW() WHERE user_id=:uid"),
            {"v": json.dumps(prefs, ensure_ascii=False), "uid": user_id},
        )
        await db.commit()
        await _classify_user_level(
            db,
            user_id=user_id,
            external_id=external_id,
            log=log,
        )
        await db.commit()
        log.bind(age=age).info("tg.profile.age_collected")
        if onboarding_done:
            return None
        next_question = _build_next_question(1, language=language) or ""
        if next_question:
            prefs = await _get_profile_prefs(db, user_id)
            prefs["onboarding_pending"] = True
            await db.execute(
                text("UPDATE user_profiles SET preferences=:v, updated_at=NOW() WHERE user_id=:uid"),
                {"v": json.dumps(prefs, ensure_ascii=False), "uid": user_id},
            )
            await db.commit()
            await _send_tg(chat_id, next_question, trace_id, typing_delay=True)
            return next_question
        return None

    if completeness.country_code is None:
        inferred_country = (
            normalize_country_code(text_content)
            or await country_from_recent_user_messages(db, user_id=user_id)
            or country_from_text_language(text_content)
        )
        if inferred_country:
            await write_country_code(
                db,
                user_id=user_id,
                country_code=inferred_country,
                source="language_fallback",
            )
            await db.commit()
            await _classify_user_level(
                db,
                user_id=user_id,
                external_id=external_id,
                log=log,
            )
            await db.commit()
            completeness = await read_profile_completeness(db, user_id=user_id)
            log.bind(country_code=inferred_country).info(
                "tg.profile.country_detected_from_language"
            )

    if completeness.country_code is None:
        prefs["profile_intake_pending"] = "country"
        await db.execute(
            text("UPDATE user_profiles SET preferences=:v, updated_at=NOW() WHERE user_id=:uid"),
            {"v": json.dumps(prefs, ensure_ascii=False), "uid": user_id},
        )
        await db.commit()
        question = _profile_copy("country_question", text_content, PROFILE_COUNTRY_QUESTION)
        await _send_tg(chat_id, question, trace_id, typing_delay=True)
        log.info("tg.profile.ask_country")
        return question

    if completeness.age is None:
        prefs["profile_intake_pending"] = "age"
        await db.execute(
            text("UPDATE user_profiles SET preferences=:v, updated_at=NOW() WHERE user_id=:uid"),
            {"v": json.dumps(prefs, ensure_ascii=False), "uid": user_id},
        )
        await db.commit()
        question = _profile_copy("age_question", text_content, PROFILE_AGE_QUESTION)
        await _send_tg(chat_id, question, trace_id, typing_delay=True)
        log.info("tg.profile.ask_age")
        return question

    return None


# ── Onboarding 消息处理 ───────────────────────────────

async def _parse_onboarding_answer(step: int, text_content: str) -> dict:
    """将用户纯文本输入转换为 OnboardingRequest.answer 格式。"""
    if step == 1:
        return {"nickname": text_content.strip()[:50]}
    elif step == 2:
        # 兴趣：逗号/顿号分隔或自由文本
        parts = [s.strip() for s in re.split(r"[,，、\s]+", text_content) if s.strip()]
        return {"interests": parts if parts else [text_content.strip()]}
    elif step == 3:
        return {"chat_style": text_content.strip()}
    elif step == 4:
        return {"forbidden_topics": text_content.strip()}
    elif step == 5:
        return {"current_intent": text_content.strip()}
    return {"text": text_content}


async def _handle_onboarding(
    db: AsyncSession,
    redis,
    user_id: str,
    conv_id: str,
    chat_id: int,
    text_content: str,
    trace_id: str,
) -> str:
    """
    处理 Onboarding 流程中的一条消息。
    返回 bot 要发给用户的回复文本（已发送），或空字符串。
    """
    log = logger.bind(trace_id=trace_id, user_id=user_id)
    prefs = await _get_profile_prefs(db, user_id)
    current_step = prefs.get("onboarding_step", 0)
    language = _detect_onboarding_language(
        text_content,
        default=_normalize_onboarding_language(prefs.get("onboarding_language")),
    )
    prefs["onboarding_language"] = language

    # 已完成
    if current_step >= ONBOARDING_STEPS + 1:
        return ""

    # 确定本次应提交的步骤
    submit_step = current_step + 1
    if submit_step > ONBOARDING_STEPS:
        return ""

    # ── 全新用户：current_step==0 且没有 pending 标记 ──
    # 第一条任意消息 → 发 Q1，设 pending，等待下一条消息作为答案
    if current_step == 0 and not prefs.get("onboarding_pending"):
        prefs["onboarding_pending"] = True
        await db.execute(
            text("UPDATE user_profiles SET preferences=:v, updated_at=NOW() WHERE user_id=:uid"),
            {"v": json.dumps(prefs, ensure_ascii=False), "uid": user_id}
        )
        await db.commit()
        q1 = _build_next_question(1, language=language) or ""
        await _send_tg(chat_id, q1, trace_id, typing_delay=True)
        log.info("onboarding.tg.sent_q1")
        return q1

    # ── 有 pending 标记（等待 step1 答案）────────────────
    if prefs.get("onboarding_pending") and current_step == 0:
        submit_step = 1

    log.info(f"onboarding.tg.step submit_step={submit_step}")

    # 解析答案
    answer = await _parse_onboarding_answer(submit_step, text_content)

    # ── 写入对应字段 ─────────────────────────────────
    import json as _json

    if submit_step == 1:
        nickname = answer.get("nickname") or _fallback_nickname(language)
        await db.execute(
            text("UPDATE users SET nickname=:nick, updated_at=NOW() WHERE id=:uid"),
            {"nick": nickname, "uid": user_id}
        )
        prefs.pop("onboarding_pending", None)
        prefs["onboarding_step"] = 1
        log.bind(nickname=nickname).info("onboarding.tg.step1_done")

    elif submit_step == 2:
        interests = answer.get("interests", [])
        await db.execute(
            text("UPDATE user_profiles SET interests=:v, updated_at=NOW() WHERE user_id=:uid"),
            {"v": _json.dumps(interests, ensure_ascii=False), "uid": user_id}
        )
        prefs["onboarding_step"] = 2
        log.bind(interests=interests).info("onboarding.tg.step2_done")

    elif submit_step == 3:
        raw = answer.get("chat_style", "1")
        chat_style = CHAT_STYLE_MAP.get(raw.lower(), "warm")
        await db.execute(
            text("UPDATE user_profiles SET chat_style=:v, updated_at=NOW() WHERE user_id=:uid"),
            {"v": chat_style, "uid": user_id}
        )
        prefs["onboarding_step"] = 3
        log.bind(chat_style=chat_style).info("onboarding.tg.step3_done")

    elif submit_step == 4:
        raw = answer.get("forbidden_topics", "")
        if isinstance(raw, str):
            if raw.strip() in ("没有", "无", "none", "no", ""):
                forbidden = []
            else:
                forbidden = [s.strip() for s in raw.replace("、", ",").split(",") if s.strip()]
        else:
            forbidden = raw
        await db.execute(
            text("UPDATE user_profiles SET forbidden_topics=:v, updated_at=NOW() WHERE user_id=:uid"),
            {"v": _json.dumps(forbidden, ensure_ascii=False), "uid": user_id}
        )
        prefs["onboarding_step"] = 4
        log.bind(forbidden=forbidden).info("onboarding.tg.step4_done")

    elif submit_step == 5:
        intent = answer.get("current_intent", "")
        prefs["current_intent"]  = intent
        prefs["onboarding_step"] = ONBOARDING_STEPS + 1   # 完成

        # 分配角色
        profile = await _load_onboarding_profile(db, user_id)
        char_info = await _assign_character(db, user_id, profile)

        # GDPR consent
        await db.execute(
            text("UPDATE users SET gdpr_consent_at=NOW(), updated_at=NOW() WHERE id=:uid"),
            {"uid": user_id}
        )
        log.bind(intent=intent, character=char_info).info("onboarding.tg.completed")

    await db.execute(
        text("UPDATE user_profiles SET preferences=:v, updated_at=NOW() WHERE user_id=:uid"),
        {"v": _json.dumps(prefs, ensure_ascii=False), "uid": user_id}
    )
    await db.commit()

    # ── 发下一个问题 or 完成消息 ──────────────────────
    next_step = submit_step + 1
    if submit_step == ONBOARDING_STEPS:
        nick_row = (await db.execute(
            text("SELECT nickname FROM users WHERE id=:uid"), {"uid": user_id}
        )).fetchone()
        nickname = (nick_row[0] if nick_row else None) or _fallback_nickname(language)
        reply = _build_completion_message(nickname, language)
    else:
        nick_row = (await db.execute(
            text("SELECT nickname FROM users WHERE id=:uid"), {"uid": user_id}
        )).fetchone()
        nickname = (nick_row[0] if nick_row else None) or _fallback_nickname(language)
        reply = _build_next_question(next_step, nickname, language) or ""

    if reply:
        await _send_tg(chat_id, reply, trace_id, typing_delay=True)
        log.bind(next_step=next_step).info("onboarding.tg.sent_next_q")

    return reply


# ── 主 Webhook 路由 ───────────────────────────────────

@router.post("/telegram/webhook")
async def telegram_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    D1-1 + D1-3 + D2-3: Telegram Webhook
    1. 幂等（Redis SET NX tg-{update_id}）
    2. 查/建 user + conversation
    3. Onboarding 流程（新用户 / 进行中）
    4. 普通 echo（Onboarding 完成后，D2-2 接入前）
    5. 持久化消息 + Redis 上下文
    """
    trace_id = _make_trace_id()
    start_ts = time.time()

    raw = await request.body()
    try:
        update = json.loads(raw)
    except Exception:
        logger.warning(f"[{trace_id}] tg.webhook.invalid_json")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    update_id = update.get("update_id")
    idem_key  = _idem_key(update_id)
    logger.info(f"[{trace_id}] tg.webhook.received update_id={update_id}")

    redis = await get_redis()

    # 幂等检查
    acquired = await redis.set(f"idem:{idem_key}", "1", nx=True, ex=IDEM_TTL_SECONDS)
    if not acquired:
        logger.info(f"[{trace_id}] tg.webhook.duplicate update_id={update_id}")
        return JSONResponse({"ok": True, "duplicate": True, "trace_id": trace_id})

    # 解析 message
    message = update.get("message") or update.get("edited_message")
    if not message:
        return JSONResponse({"ok": True, "trace_id": trace_id})

    tg_user       = message.get("from", {})
    tg_user_id    = str(tg_user.get("id", ""))
    tg_chat_id    = message.get("chat", {}).get("id")
    tg_message_id = message.get("message_id")
    text_content  = message.get("text") or message.get("caption") or "[non-text]"

    if not tg_user_id:
        return JSONResponse({"ok": True, "trace_id": trace_id})

    if text_content.startswith("/"):
        command_reply = await _handle_command(text_content)
        if command_reply is not None:
            await _send_tg(tg_chat_id, command_reply, trace_id)
            logger.info(
                f"[{trace_id}] tg.command.handled command={text_content.split()[0]}"
            )
            return JSONResponse(
                {
                    "ok": True,
                    "trace_id": trace_id,
                    "command_handled": True,
                }
            )

    external_id = f"tg_{tg_user_id}"
    channel     = "telegram"

    log = logger.bind(
        trace_id=trace_id,
        external_id=external_id,
        tg_msg_id=tg_message_id,
        chat_id=tg_chat_id,
    )

    # ── 查/建 user ────────────────────────────────────
    user_id = await _get_or_create_user(db, channel, external_id)
    log = log.bind(user_id=user_id)
    await _persist_technical_country_hint(
        db,
        user_id=user_id,
        tg_user=tg_user,
        log=log,
    )
    await _classify_user_level(
        db,
        user_id=user_id,
        external_id=external_id,
        log=log,
    )
    await db.commit()
    user_status_row = (
        await db.execute(
            text("SELECT status, is_minor_suspected FROM users WHERE id=:uid"),
            {"uid": user_id},
        )
    ).fetchone()
    user_status = str(user_status_row[0] or "active") if user_status_row else "active"
    is_minor_suspected = (
        bool(user_status_row[1]) if user_status_row and len(user_status_row) > 1 else False
    )
    if user_status != "active":
        log.bind(user_status=user_status).info("tg.user_status_blocked")
        return JSONResponse(
            {
                "ok": True,
                "trace_id": trace_id,
                "blocked": True,
                "block_reason": f"user_status:{user_status}",
            }
        )

    # ── 查/建 conversation ────────────────────────────
    conv_row = (await db.execute(
        text(
            "SELECT id FROM conversations "
            "WHERE user_id=:uid AND state NOT IN ('CLOSED','ESCALATED') "
            "ORDER BY updated_at DESC LIMIT 1"
        ),
        {"uid": user_id}
    )).fetchone()

    if conv_row:
        conv_id = str(conv_row[0])
        log.bind(conv_id=conv_id).info("tg.conversation.found")
    else:
        conv_id = str(uuid.uuid4())
        await db.execute(
            text("INSERT INTO conversations (id,user_id,channel,state) VALUES (:id,:uid,:ch,'AI_ACTIVE')"),
            {"id": conv_id, "uid": user_id, "ch": channel}
        )
        await db.commit()
        log.bind(conv_id=conv_id).info("tg.conversation.created")

    # ── Onboarding 状态 + 未成年人保护 + 内容安全 ────────────────
    prefs = await _get_profile_prefs(db, user_id)
    onboarding_step = prefs.get("onboarding_step", 0)
    onboarding_done = onboarding_step >= ONBOARDING_STEPS + 1

    safety_result: dict | None = None
    safety_blocked = False
    if text_content != "[non-text]":
        minor_decision = await evaluate_inbound_minor_protection(
            db,
            user_id=user_id,
            text_value=text_content,
            is_minor_suspected=is_minor_suspected,
        )
        if (
            minor_decision.suspected_minor
            or minor_decision.adult_content
            or minor_decision.updated_user
        ):
            safety_result = minor_decision.as_safety_layer()
        safety_blocked = bool(minor_decision.blocked)

    if (
        onboarding_done
        and text_content != "[non-text]"
        and settings.CONTENT_SAFETY_ENABLED
    ):
        content_safety_result = await evaluate_inbound_content_safety(
            text_content, trace_id=trace_id
        )
        if safety_result is None:
            safety_result = content_safety_result
        else:
            safety_result = {
                **content_safety_result,
                "minor_protection": safety_result.get("minor_protection"),
            }
        safety_blocked = safety_blocked or bool(content_safety_result.get("blocked"))

    # ── 持久化用户消息 ────────────────────────────────
    msg_id = await _persist_message(
        db,
        conv_id,
        "user",
        user_id,
        text_content,
        safety_result=safety_result,
    )
    log.bind(msg_id=msg_id).info("tg.message.persisted")

    if safety_blocked:
        await _send_tg(
            tg_chat_id,
            "这个话题我没办法聊，换个方向说说？",
            trace_id,
        )
        log.bind(
            block_reason=safety_result.get("block_reason") if safety_result else None
        ).info("tg.content_safety.blocked")
        elapsed = (time.time() - start_ts) * 1000
        log.bind(elapsed_ms=round(elapsed, 1)).info("tg.webhook.complete")
        return JSONResponse(
            {
                "ok": True,
                "trace_id": trace_id,
                "message_id": msg_id,
                "safety_blocked": True,
            }
        )

    # Redis 上下文：用户消息
    try:
        await _push_context(redis, conv_id, "user", text_content, msg_id)
    except Exception as e:
        log.warning(f"tg.context.push_failed err={e}")

    # ── 决策：Onboarding 还是普通对话 ─────────────────
    # prefs / onboarding_done 已在上文计算
    intake_reply = await _handle_required_profile_intake(
        db,
        user_id=user_id,
        chat_id=tg_chat_id,
        text_content=text_content,
        trace_id=trace_id,
        onboarding_done=onboarding_done,
        language=_normalize_onboarding_language(prefs.get("onboarding_language")),
        external_id=external_id,
        log=log,
    )
    if intake_reply:
        try:
            bot_msg_id = await _persist_message(
                db,
                conv_id,
                "assistant",
                "bot",
                intake_reply,
            )
            await _push_context(redis, conv_id, "assistant", intake_reply, bot_msg_id)
            log.bind(bot_msg_id=bot_msg_id).info("tg.profile_intake.persisted")
        except Exception as e:
            log.warning(f"tg.profile_intake.persist_failed err={e}")
        elapsed = (time.time() - start_ts) * 1000
        log.bind(elapsed_ms=round(elapsed, 1), onboarding_done=onboarding_done).info(
            "tg.webhook.complete"
        )
        return JSONResponse(
            {
                "ok": True,
                "trace_id": trace_id,
                "message_id": msg_id,
                "onboarding_done": onboarding_done,
                "profile_intake": True,
            }
        )

    # ── D3-3: 触发记忆写入（fire-and-forget）──────────
    # 只在 onboarding 完成后写；onboarding 期间的事实由 user_profiles 承接。
    # 注意：不传 db（请求 session 会先于背景任务关闭），memory_writer 自开 session。
    try:
        asyncio.create_task(
            maybe_write_memory(
                user_id=user_id,
                conversation_id=conv_id,
                message_id=msg_id,
                content=text_content,
                trace_id=trace_id,
                redis=redis,
                is_onboarding=not onboarding_done,
            )
        )
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning(
            "tg.memory_writer.spawn_failed"
        )

    # P2-04: persist the user's age only when AI confidence passes the write gate.
    try:
        asyncio.create_task(
            maybe_extract_and_write_age(
                user_id=user_id,
                content=text_content,
                trace_id=trace_id,
            )
        )
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning(
            "tg.age_extraction.spawn_failed"
        )

    bot_reply = None
    bot_reply_message_id = None
    bot_consistency_score = None

    if not onboarding_done:
        # Onboarding 模式
        bot_text = await _handle_onboarding(
            db, redis, user_id, conv_id, tg_chat_id, text_content, trace_id
        )
        if bot_text:
            bot_reply = bot_text
    else:
        # 普通模式：通过 LLM Orchestrator 生成回复（D2-2 / D2-2.1：带 Redis 短期上下文）
        try:
            reply_text = await generate_reply(
                user_id=user_id,
                conversation_id=conv_id,
                user_text=text_content,
                trace_id=trace_id,
                redis=redis,
                db=db,
                trigger_message_id=msg_id,
            )
        except LLMOrchestratorError as exc:
            log.bind(result="failed", reason=str(exc)).warning("tg.orchestrator.failed")
            reply_text = "现在有点忙，稍后再聊好吗？"

        try:
            ctx = await load_reply_consistency_context(db, conv_id)
        except Exception as exc:
            log.bind(error_type=type(exc).__name__).warning(
                "tg.consistency.context_failed"
            )
            ctx = {}
        consistency = evaluate_reply_consistency(
            reply_text=reply_text,
            character=ctx.get("character"),
        )
        reply_text = consistency.output_text
        bot_consistency_score = consistency.score
        log.bind(**consistency.as_log_dict()).info("tg.consistency.checked")

        app_download_decision = get_last_app_download_decision()
        bot_reply_message_id = str(uuid.uuid4())
        try:
            reply_text = await wrap_text_links_with_tracking(
                db,
                text_value=reply_text,
                base_url=str(request.base_url).rstrip("/"),
                user_id=user_id,
                conversation_id=conv_id,
                message_id=bot_reply_message_id,
                script_hit_id=(
                    app_download_decision.script_hit_id
                    if app_download_decision is not None
                    else None
                ),
                platform="telegram_bot",
                scene_step=(
                    app_download_decision.scene_step
                    if app_download_decision is not None
                    else None
                ),
                script_category=(
                    app_download_decision.category_key
                    if app_download_decision is not None
                    else None
                ),
                persona_slug=(
                    app_download_decision.persona_slug
                    if app_download_decision is not None
                    else None
                ),
                intent=(
                    app_download_decision.intent
                    if app_download_decision is not None
                    else None
                ),
                country_code=(
                    app_download_decision.country_code
                    if app_download_decision is not None
                    else None
                ),
                age=app_download_decision.age if app_download_decision is not None else None,
                user_level=(
                    app_download_decision.user_level
                    if app_download_decision is not None
                    else None
                ),
                is_t1_country=(
                    app_download_decision.is_t1_country
                    if app_download_decision is not None
                    else None
                ),
                metadata={"source": "telegram_bot_reply", "trace_id": trace_id},
            )
        except Exception as exc:
            log.bind(error_type=type(exc).__name__).warning("tg.link_attribution_failed")

        telegram_reply_text = render_tracking_links_as_html_cta(reply_text)
        sent_id = await _send_tg(tg_chat_id, telegram_reply_text, trace_id, typing_delay=True)
        if sent_id is not None and app_download_decision is not None:
            for asset in app_download_decision.assets:
                asset_mid = await send_telegram_bot_asset(
                    chat_id=tg_chat_id,
                    asset=asset,
                    trace_id=trace_id,
                )
                if asset_mid is not None:
                    await db.execute(
                        text(
                            "INSERT INTO messages "
                            "(id,conversation_id,sender_type,sender_id,content,content_type) "
                            "VALUES (:id,:cid,'assistant','bot',:content,:content_type)"
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "cid": conv_id,
                            "content": asset.get("asset_url") or "",
                            "content_type": asset.get("asset_type") or "media",
                        },
                    )
                    await db.commit()
        if sent_id is not None:
            bot_reply = reply_text
            log.bind(result="success").info("tg.bot_reply.sent")

    # ── 持久化 bot 回复 ───────────────────────────────
    if bot_reply:
        try:
            bot_msg_id = await _persist_message(
                db,
                conv_id,
                "assistant",
                "bot",
                bot_reply,
                consistency_score=bot_consistency_score,
                message_id=bot_reply_message_id,
            )
            await _push_context(redis, conv_id, "assistant", bot_reply, bot_msg_id)
            log.bind(bot_msg_id=bot_msg_id).info("tg.bot_reply.persisted")
        except Exception as e:
            log.warning(f"tg.bot_reply.persist_failed err={e}")

    elapsed = (time.time() - start_ts) * 1000
    log.bind(elapsed_ms=round(elapsed, 1), onboarding_done=onboarding_done).info("tg.webhook.complete")

    return JSONResponse({
        "ok":             True,
        "trace_id":       trace_id,
        "message_id":     msg_id,
        "onboarding_done": onboarding_done,
    })


@router.get("/telegram/webhook/info")
async def webhook_info():
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        return {"error": "TELEGRAM_BOT_TOKEN not set"}
    async with httpx.AsyncClient() as client:
        r = await client.get(f"https://api.telegram.org/bot{token}/getWebhookInfo")
        return r.json()
