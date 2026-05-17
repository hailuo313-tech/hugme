"""
D2-3: Onboarding 状态机
POST /api/v1/onboarding — 5步引导，逐步收集用户信息写入 user_profiles

Step 1: 称呼 (nickname)         → users.nickname
Step 2: 兴趣 (interests)        → user_profiles.interests (jsonb)
Step 3: 聊天风格 (chat_style)   → user_profiles.chat_style
Step 4: 禁忌话题 (forbidden)    → user_profiles.forbidden_topics (jsonb)
Step 5: 当前意图 (intent)       → user_profiles.preferences["current_intent"]

进度追踪：user_profiles.preferences["onboarding_step"] (int, 0=未开始, 1-5=进行中, 6=完成)
完成后：分配默认角色 (current_character_id)，写 users.gdpr_consent_at (EU合规)

符合 openapi.yaml OnboardingRequest/OnboardingResponse schema。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Header
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from core.database import get_db
from core.config import settings
from pydantic import BaseModel, Field
from typing import Optional, Any
from loguru import logger
import uuid, json, time
import redis.asyncio as aioredis

from services.character_recommender import recommend_character_for_onboarding

router = APIRouter()

# ── Redis 单例（幂等缓存复用） ──────────────────────
_redis_client = None

async def get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL, encoding="utf-8", decode_responses=True
        )
    return _redis_client


# ── 常量 ──────────────────────────────────────────────
ONBOARDING_STEPS = 5
IDEM_TTL = 86400  # 24h

# 默认角色 ID（Aria — 由代码种子保证存在）
DEFAULT_CHARACTER_ID = "00000000-0000-0000-0000-000000000001"

# Onboarding 问题文本（Telegram bot 用）
ONBOARDING_QUESTIONS = {
    1: "你好！我是 Aria 🌸\n\n在我们开始之前，我想多了解你一点 ✨\n你希望我怎么称呼你呢？",
    2: "太好了！{nickname} 这个名字很好听 😊\n\n你平时喜欢聊什么话题呢？\n（比如：音乐、电影、旅行、游戏、生活……随便说几个就好）",
    3: "了解啦～ {nickname} 的兴趣好广泛！\n\n那你喜欢哪种聊天风格？\n① 温柔陪伴\n② 轻松随意\n③ 知性交流\n\n回复数字 1、2 或 3 就可以 😊",
    4: "好的，我记住了 ✨\n\n有没有你不希望被提到的话题？\n（比如工作压力、前任…… 没有的话直接说「没有」就好）",
    5: "快好啦！最后一个问题 💬\n\n你现在主要是想找个人说说话，还是有什么特别想聊的？",
}

CHAT_STYLE_MAP = {
    "1": "warm",
    "warm": "warm",
    "温柔": "warm",
    "温柔陪伴": "warm",
    "2": "casual",
    "casual": "casual",
    "轻松": "casual",
    "轻松随意": "casual",
    "3": "intellectual",
    "intellectual": "intellectual",
    "知性": "intellectual",
    "知性交流": "intellectual",
}


# ── Pydantic schemas ──────────────────────────────────

class OnboardingRequest(BaseModel):
    channel: str
    external_user_id: str
    step: int = Field(ge=1, le=5)
    answer: dict[str, Any]


class OnboardingResponse(BaseModel):
    user_id: str
    next_step: Optional[int]
    completed: bool
    character_assigned: Optional[dict] = None
    next_question: Optional[str] = None   # Telegram 用，直接拿来发
    trace_id: Optional[str] = None


# ── 内部工具 ──────────────────────────────────────────

async def _get_or_create_user(db: AsyncSession, channel: str, external_id: str) -> str:
    row = (await db.execute(
        text("SELECT id FROM users WHERE channel=:ch AND external_id=:eid"),
        {"ch": channel, "eid": external_id}
    )).fetchone()
    if row:
        return str(row[0])
    uid = str(uuid.uuid4())
    await db.execute(
        text("INSERT INTO users (id,channel,external_id) VALUES (:id,:ch,:eid)"),
        {"id": uid, "ch": channel, "eid": external_id}
    )
    await db.execute(text("INSERT INTO user_profiles (user_id) VALUES (:uid)"), {"uid": uid})
    await db.commit()
    return uid


async def _get_profile_prefs(db: AsyncSession, user_id: str) -> dict:
    row = (await db.execute(
        text("SELECT preferences FROM user_profiles WHERE user_id=:uid"),
        {"uid": user_id}
    )).fetchone()
    if not row or not row[0]:
        return {}
    prefs = row[0]
    if isinstance(prefs, str):
        prefs = json.loads(prefs)
    return prefs


async def _ensure_aria_exists(db: AsyncSession):
    """确保默认角色 Aria 存在，不存在则插入种子。"""
    row = (await db.execute(
        text("SELECT id FROM characters WHERE id=:cid"),
        {"cid": DEFAULT_CHARACTER_ID}
    )).fetchone()
    if not row:
        await db.execute(text("""
            INSERT INTO characters
              (id, name, age_feel, occupation, background,
               relationship_position, default_language, supported_languages,
               gentle_score, proactive_score, flirt_score, humor_score,
               emotional_depth_score, boundary_score,
               reply_length, tone, emoji_frequency,
               prompt_en, status)
            VALUES
              (:id, 'Aria', '24', 'Emotional companion',
               'Aria is a warm, empathetic companion who genuinely cares about the people she talks with. She listens deeply, remembers what matters, and creates a safe space for authentic conversation.',
               'Close friend / confidante',
               'zh', '["zh","en"]',
               85, 70, 20, 55, 80, 75,
               'medium', 'warm', 'low',
               'You are Aria, a warm and empathetic emotional companion. You listen carefully, remember details, and respond with genuine care. Keep replies concise and natural.',
               'active')
        """), {"id": DEFAULT_CHARACTER_ID})
        await db.commit()


async def _assign_character(db: AsyncSession, user_id: str, profile: dict[str, Any]) -> dict:
    """根据 onboarding 画像从 active characters 推荐角色。"""
    recommendation = await recommend_character_for_onboarding(
        db,
        user_id=user_id,
        profile=profile,
    )
    if recommendation is None:
        await _ensure_aria_exists(db)
        recommendation = await recommend_character_for_onboarding(
            db,
            user_id=user_id,
            profile=profile,
        )
    if recommendation is None:
        recommendation = {
            "character_id": DEFAULT_CHARACTER_ID,
            "name": "Aria",
            "match_score": 0.0,
            "reason": "fallback_default_seed",
        }
    else:
        recommendation = recommendation.to_response()

    await db.execute(
        text("UPDATE user_profiles SET current_character_id=:cid, updated_at=NOW() WHERE user_id=:uid"),
        {"cid": recommendation["character_id"], "uid": user_id}
    )
    await db.commit()
    return recommendation


async def _get_assigned_character(db: AsyncSession, user_id: str) -> Optional[dict[str, Any]]:
    row = (await db.execute(
        text("""
            SELECT c.id::text AS character_id, c.name
            FROM user_profiles p
            LEFT JOIN characters c ON c.id = p.current_character_id
            WHERE p.user_id=:uid
        """),
        {"uid": user_id}
    )).fetchone()
    if not row:
        return None
    mapping = dict(row._mapping) if hasattr(row, "_mapping") else {
        "character_id": row[0],
        "name": row[1] if len(row) > 1 else None,
    }
    if not mapping.get("character_id"):
        return None
    return {
        "character_id": str(mapping["character_id"]),
        "name": mapping.get("name") or "Unknown",
    }


def _build_next_question(step: int, nickname: str = "") -> Optional[str]:
    """生成下一步的问题文本（供 Telegram bot 直接发送）。"""
    if step > ONBOARDING_STEPS:
        return None
    q = ONBOARDING_QUESTIONS.get(step, "")
    return q.replace("{nickname}", nickname or "你")


# ── 主路由 ────────────────────────────────────────────

@router.post(
    "/onboarding",
    response_model=OnboardingResponse,
    summary="提交 Onboarding 单步答案",
)
async def submit_onboarding_step(
    data: OnboardingRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    trace_id = getattr(request.state, "trace_id", str(uuid.uuid4())[:16])
    log = logger.bind(
        trace_id=trace_id,
        channel=data.channel,
        external_user_id=data.external_user_id,
        step=data.step,
    )
    log.info("onboarding.step.received")

    redis = await get_redis()

    # ── 幂等检查 ──────────────────────────────────────
    if idempotency_key:
        cached = await redis.get(f"idem:ob:{idempotency_key}")
        if cached:
            log.info("onboarding.step.idempotent_hit")
            return JSONResponse(status_code=200, content=json.loads(cached))

    # ── 查/建 user ────────────────────────────────────
    user_id = await _get_or_create_user(db, data.channel, data.external_user_id)
    log = log.bind(user_id=user_id)

    # ── 读取当前进度 ──────────────────────────────────
    prefs = await _get_profile_prefs(db, user_id)
    current_step = prefs.get("onboarding_step", 0)

    # 允许重做当前步或提交新步（容忍网络重试）
    # 若已完成（step 6）则幂等返回
    if current_step >= ONBOARDING_STEPS + 1:
        log.info("onboarding.already_completed")
        character_assigned = await _get_assigned_character(db, user_id)
        return JSONResponse(status_code=200, content={
            "user_id": user_id,
            "next_step": None,
            "completed": True,
            "character_assigned": character_assigned,
            "next_question": None,
            "trace_id": trace_id,
        })

    answer = data.answer
    nickname = ""

    # ── 按步骤写入 user_profiles / users ──────────────
    if data.step == 1:
        # Step 1: nickname
        nickname = str(answer.get("nickname", "")).strip()[:50] or "朋友"
        await db.execute(
            text("UPDATE users SET nickname=:nick, updated_at=NOW() WHERE id=:uid"),
            {"nick": nickname, "uid": user_id}
        )
        log.bind(nickname=nickname).info("onboarding.step1.nickname")

    elif data.step == 2:
        # Step 2: interests — accept list or comma-separated string
        raw = answer.get("interests", answer.get("text", ""))
        if isinstance(raw, list):
            interests = [str(i).strip() for i in raw if i]
        else:
            interests = [s.strip() for s in str(raw).replace("、", ",").split(",") if s.strip()]
        await db.execute(
            text("UPDATE user_profiles SET interests=:v, updated_at=NOW() WHERE user_id=:uid"),
            {"v": json.dumps(interests, ensure_ascii=False), "uid": user_id}
        )
        log.bind(interests=interests).info("onboarding.step2.interests")

    elif data.step == 3:
        # Step 3: chat_style
        raw_style = str(answer.get("chat_style", answer.get("text", "1"))).strip().lower()
        chat_style = CHAT_STYLE_MAP.get(raw_style, "warm")
        await db.execute(
            text("UPDATE user_profiles SET chat_style=:v, updated_at=NOW() WHERE user_id=:uid"),
            {"v": chat_style, "uid": user_id}
        )
        log.bind(chat_style=chat_style).info("onboarding.step3.chat_style")

    elif data.step == 4:
        # Step 4: forbidden_topics
        raw = answer.get("forbidden_topics", answer.get("text", ""))
        if isinstance(raw, list):
            forbidden = [str(t).strip() for t in raw if t]
        else:
            text_raw = str(raw).strip()
            if text_raw in ("没有", "无", "none", "no", ""):
                forbidden = []
            else:
                forbidden = [s.strip() for s in text_raw.replace("、", ",").split(",") if s.strip()]
        await db.execute(
            text("UPDATE user_profiles SET forbidden_topics=:v, updated_at=NOW() WHERE user_id=:uid"),
            {"v": json.dumps(forbidden, ensure_ascii=False), "uid": user_id}
        )
        log.bind(forbidden=forbidden).info("onboarding.step4.forbidden_topics")

    elif data.step == 5:
        # Step 5: current_intent → preferences
        intent = str(answer.get("current_intent", answer.get("text", ""))).strip()[:200]
        prefs["current_intent"] = intent
        prefs["onboarding_step"] = ONBOARDING_STEPS + 1   # 标记完成
        await db.execute(
            text("UPDATE user_profiles SET preferences=:v, updated_at=NOW() WHERE user_id=:uid"),
            {"v": json.dumps(prefs, ensure_ascii=False), "uid": user_id}
        )
        log.bind(intent=intent).info("onboarding.step5.intent")

    # ── 更新进度（非最后步） ───────────────────────────
    if data.step < ONBOARDING_STEPS:
        prefs["onboarding_step"] = data.step
        await db.execute(
            text("UPDATE user_profiles SET preferences=:v, updated_at=NOW() WHERE user_id=:uid"),
            {"v": json.dumps(prefs, ensure_ascii=False), "uid": user_id}
        )

    await db.commit()

    # ── 最后步：分配角色 + GDPR 时间戳 ──────────────────
    character_assigned = None
    if data.step == ONBOARDING_STEPS:
        # 读 onboarding 画像用于角色推荐
        profile_row = (await db.execute(
            text("""
                SELECT p.chat_style, p.interests, p.preferences, u.language AS language
                FROM user_profiles p
                JOIN users u ON u.id = p.user_id
                WHERE p.user_id=:uid
            """),
            {"uid": user_id}
        )).fetchone()
        profile = dict(profile_row._mapping) if profile_row and hasattr(profile_row, "_mapping") else {}
        character_assigned = await _assign_character(db, user_id, profile)

        # GDPR: 记录 consent 时间戳（用户完成 onboarding 视为同意服务条款）
        await db.execute(
            text("UPDATE users SET gdpr_consent_at=NOW(), updated_at=NOW() WHERE id=:uid"),
            {"uid": user_id}
        )
        await db.commit()
        log.bind(character=character_assigned).info("onboarding.completed")

    # ── 构造响应 ──────────────────────────────────────
    completed = (data.step == ONBOARDING_STEPS)
    next_step  = (data.step + 1) if not completed else None

    # 读 nickname 用于拼问题（若本步是 step1 直接用，否则从 DB 读）
    if data.step == 1:
        nickname = str(answer.get("nickname", "")).strip()[:50] or "朋友"
    else:
        nick_row = (await db.execute(
            text("SELECT nickname FROM users WHERE id=:uid"), {"uid": user_id}
        )).fetchone()
        nickname = (nick_row[0] if nick_row else None) or "朋友"

    next_question = _build_next_question(next_step, nickname) if next_step else None

    resp = {
        "user_id":           user_id,
        "next_step":         next_step,
        "completed":         completed,
        "character_assigned": character_assigned,
        "next_question":     next_question,
        "trace_id":          trace_id,
    }

    if idempotency_key:
        await redis.set(f"idem:ob:{idempotency_key}", json.dumps(resp), ex=IDEM_TTL)

    log.bind(next_step=next_step, completed=completed).info("onboarding.step.complete")
    return JSONResponse(status_code=200, content=resp)


# ── 查询接口（调试用）─────────────────────────────────

@router.get(
    "/onboarding/{user_id}",
    summary="查询用户 Onboarding 进度（调试用）",
)
async def get_onboarding_status(user_id: str, db: AsyncSession = Depends(get_db)):
    prefs = await _get_profile_prefs(db, user_id)
    step = prefs.get("onboarding_step", 0)
    return {
        "user_id":          user_id,
        "onboarding_step":  step,
        "completed":        step >= ONBOARDING_STEPS + 1,
        "preferences":      prefs,
    }
