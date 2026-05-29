from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import Any

from loguru import logger
from sqlalchemy import text

from core.config import settings
from services.app_download_platforms import resolve_app_download_url
from services.emotion_lexicon import detect_language_from_text, normalize_language
from services.level_engine import country_tier
from services.profile_intake import age_from_preferences, normalize_country_code
from services.script_match_hooks import (
    ScriptMatchContext,
    ScriptMatchResult,
    record_script_match_result,
)
from services.script_template_retriever import (
    ScriptTemplateQuery,
    search_script_templates,
)


APP_DOWNLOAD_CATEGORIES = {
    "app_download_first_push",
    "app_download_after_warmup",
    "app_download_direct_cta",
    "app_download_objection",
    "trust_reassurance",
    "app_link_clicked_followup",
    "operator_app_conversion",
}

APP_DOWNLOAD_SAFETY_TAG = "app_download_conversion"
ASSET_KEYWORD_TRIGGER_TITLES: tuple[str, ...] = (
    "用户聊天中想要看本人视频的关键词",
    "用户聊天中想要看本人图片的关键词",
)
_last_decision: contextvars.ContextVar["AppDownloadDecision | None"] = contextvars.ContextVar(
    "last_app_download_decision",
    default=None,
)


@dataclass(frozen=True)
class AppDownloadDecision:
    content: str
    category_key: str
    script_hit_id: str
    assets: list[dict[str, Any]]
    user_level: str
    persona_slug: str | None
    intent: str
    scene_step: str
    country_code: str | None
    age: int | None
    is_t1_country: bool | None


@dataclass(frozen=True)
class _FunnelState:
    tracking_id: str | None = None
    script_category: str | None = None
    minutes_since_link: float | None = None
    clicked: bool = False
    downloaded: bool = False
    registered: bool = False
    paid: bool = False


def clear_last_app_download_decision() -> None:
    _last_decision.set(None)


def get_last_app_download_decision() -> AppDownloadDecision | None:
    return _last_decision.get()


async def maybe_select_app_download_reply(
    *,
    db: Any,
    user_id: str,
    conversation_id: str,
    user_text: str,
    profile_row: dict[str, Any] | None,
    character_row: dict[str, Any] | None,
    assistant_reply_count: int | None,
    trigger_message_id: str | None,
    trace_id: str,
    classified_intent: str | None = None,
) -> AppDownloadDecision | None:
    """Return an approved App-download conversion script when the funnel calls for it.

    The selector is deliberately conservative: missing App URL, incomplete profile,
    S5 recovery, recent unclicked links, or no matching approved template all fall
    through to the existing LLM path.
    """
    clear_last_app_download_decision()
    destination_url = await resolve_app_download_url(db)
    if not settings.APP_DOWNLOAD_CONVERSION_ENABLED or not destination_url:
        return None
    if db is None:
        return None
    profile = profile_row or {}
    if _relationship_stage(profile) == "S5":
        return None

    user_level = str(profile.get("user_level") or "C").upper()
    country_code = normalize_country_code(
        profile.get("country_code")
        or _preferences(profile).get("country_code")
    )
    age = age_from_preferences(_preferences(profile))
    if user_level == "D":
        return None

    asset_trigger = await _match_asset_keyword_trigger(
        db=db,
        user_text=user_text,
        user_level=user_level,
        persona_slug=_persona_slug(character_row),
        language=_reply_language(profile, user_text),
    )
    if asset_trigger is not None:
        hit, matched_keyword = asset_trigger
        assets = await _load_script_assets(db=db, script_template_id=hit["id"])
        if assets:
            is_t1 = country_tier(country_code) == "T1" if country_code else None
            decision = AppDownloadDecision(
                content=str(hit.get("content") or ""),
                category_key=str(hit.get("category_key") or "app_download_first_push"),
                script_hit_id=str(hit["id"]),
                assets=assets,
                user_level=user_level,
                persona_slug=hit.get("persona_slug") or _persona_slug(character_row),
                intent="asset_keyword_request",
                scene_step=f"asset_keyword:{matched_keyword}",
                country_code=country_code,
                age=age,
                is_t1_country=is_t1,
            )
            _last_decision.set(decision)
            await _audit_decision(
                db=db,
                decision=decision,
                conversation_id=conversation_id,
                trigger_message_id=trigger_message_id,
                user_text=user_text,
                trace_id=trace_id,
            )
            logger.bind(
                component="app_download_conversion",
                trace_id=trace_id,
                category_key=decision.category_key,
                script_hit_id=decision.script_hit_id,
                matched_keyword=matched_keyword,
                asset_count=len(assets),
            ).info("app_download_conversion.asset_keyword_selected")
            return decision

    state = await _load_latest_funnel_state(
        db=db,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    category_key, intent, scene_step = _choose_category(
        user_text=user_text,
        state=state,
        assistant_reply_count=assistant_reply_count,
        user_level=user_level,
        classified_intent=classified_intent,
    )
    if category_key is None:
        return None

    persona_slug = _persona_slug(character_row)
    result = await search_script_templates(
        db=db,
        query=ScriptTemplateQuery(
            query=_script_query(user_text, category_key, classified_intent),
            platform="telegram_real_user",
            user_level=user_level,
            persona_slug=persona_slug,
            hook="reply",
            category_key=category_key,
            language=_reply_language(profile, user_text),
            limit=3,
        ),
        trace_id=trace_id,
    )
    if not result.hits:
        return None

    hit = result.hits[0]
    assets = await _load_script_assets(db=db, script_template_id=hit.id)
    is_t1 = country_tier(country_code) == "T1" if country_code else None
    content = _render_script(
        hit.content,
        app_download_url=destination_url,
    )
    decision = AppDownloadDecision(
        content=content,
        category_key=hit.category_key,
        script_hit_id=hit.id,
        assets=assets,
        user_level=user_level,
        persona_slug=hit.persona_slug or persona_slug,
        intent=intent,
        scene_step=scene_step,
        country_code=country_code,
        age=age,
        is_t1_country=is_t1,
    )
    _last_decision.set(decision)
    await _audit_decision(
        db=db,
        decision=decision,
        conversation_id=conversation_id,
        trigger_message_id=trigger_message_id,
        user_text=user_text,
        trace_id=trace_id,
    )
    logger.bind(
        component="app_download_conversion",
        trace_id=trace_id,
        category_key=decision.category_key,
        user_level=user_level,
        scene_step=scene_step,
    ).info("app_download_conversion.script_selected")
    return decision


async def _load_latest_funnel_state(
    *,
    db: Any,
    user_id: str,
    conversation_id: str,
) -> _FunnelState:
    row = (
        await db.execute(
            text(
                """
                SELECT
                    l.tracking_id,
                    l.script_category,
                    EXTRACT(EPOCH FROM (NOW() - l.created_at)) / 60.0 AS minutes_since_link,
                    COALESCE(bool_or(e.event_type = 'click'), FALSE) AS clicked,
                    COALESCE(bool_or(e.event_type = 'download'), FALSE) AS downloaded,
                    COALESCE(bool_or(e.event_type = 'app_register'), FALSE) AS registered,
                    COALESCE(bool_or(e.event_type = 'payment'), FALSE) AS paid
                FROM attribution_links l
                LEFT JOIN attribution_events e ON e.tracking_id = l.tracking_id
                WHERE l.user_id = CAST(:user_id AS uuid)
                  AND l.conversation_id = CAST(:conversation_id AS uuid)
                  AND (
                    l.script_category LIKE 'app_%'
                    OR l.script_category = 'trust_reassurance'
                    OR l.script_category = 'operator_app_conversion'
                  )
                GROUP BY l.tracking_id, l.script_category, l.created_at
                ORDER BY l.created_at DESC
                LIMIT 1
                """
            ),
            {"user_id": user_id, "conversation_id": conversation_id},
        )
    ).fetchone()
    if row is None:
        return _FunnelState()
    data = row._mapping if hasattr(row, "_mapping") else row
    return _FunnelState(
        tracking_id=str(data["tracking_id"]) if data.get("tracking_id") else None,
        script_category=data.get("script_category"),
        minutes_since_link=float(data.get("minutes_since_link") or 0),
        clicked=bool(data.get("clicked")),
        downloaded=bool(data.get("downloaded")),
        registered=bool(data.get("registered")),
        paid=bool(data.get("paid")),
    )


async def _load_script_assets(*, db: Any, script_template_id: str) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            """
            SELECT id, asset_type, asset_url, mime_type, caption, sort_order
            FROM script_template_assets
            WHERE script_template_id = CAST(:id AS uuid)
              AND is_active = TRUE
            ORDER BY sort_order ASC, created_at ASC
            """
        ),
        {"id": script_template_id},
    )
    return [dict(row._mapping) for row in result.fetchall()]


async def _match_asset_keyword_trigger(
    *,
    db: Any,
    user_text: str,
    user_level: str,
    persona_slug: str | None,
    language: str,
) -> tuple[dict[str, Any], str] | None:
    text_value = _normalize_keyword_text(user_text)
    if not text_value:
        return None
    result = await db.execute(
        text(
            """
            SELECT id, category_key, title, content, language, platform,
                   user_level, persona_slug, hook
            FROM script_templates
            WHERE status = 'approved'
              AND title = ANY(:titles)
              AND hook = 'reply'
              AND (platform = 'telegram_real_user' OR platform IS NULL)
              AND (user_level = :user_level OR user_level IS NULL)
              AND (persona_slug = :persona_slug OR persona_slug IS NULL OR :persona_slug IS NULL)
              AND language IN (:language, 'en')
            ORDER BY
              CASE title
                WHEN :video_title THEN 0
                WHEN :image_title THEN 1
                ELSE 2
              END,
              CASE WHEN language = :language THEN 0 ELSE 1 END,
              updated_at DESC,
              created_at DESC
            LIMIT 10
            """
        ),
        {
            "titles": list(ASSET_KEYWORD_TRIGGER_TITLES),
            "video_title": ASSET_KEYWORD_TRIGGER_TITLES[0],
            "image_title": ASSET_KEYWORD_TRIGGER_TITLES[1],
            "language": language or "en",
            "user_level": user_level,
            "persona_slug": persona_slug,
        },
    )
    for row in result.fetchall():
        data = dict(row._mapping)
        for keyword in _split_asset_keywords(str(data.get("content") or "")):
            if _keyword_matches(text_value, keyword):
                return data, keyword
    return None


def _split_asset_keywords(content: str) -> list[str]:
    normalized = (
        str(content or "")
        .replace("\r", "\n")
        .replace("，", ",")
        .replace("、", ",")
        .replace("；", ",")
        .replace(";", ",")
        .replace("`", ",")
    )
    keywords: list[str] = []
    seen: set[str] = set()
    for part in normalized.replace("\n", ",").split(","):
        keyword = part.strip().strip(".!? ")
        key = _normalize_keyword_text(keyword)
        if key and key not in seen:
            keywords.append(keyword)
            seen.add(key)
    return keywords


def _keyword_matches(normalized_text: str, keyword: str) -> bool:
    key = _normalize_keyword_text(keyword)
    return bool(key and key in normalized_text)


def _normalize_keyword_text(value: str) -> str:
    return " ".join(str(value or "").casefold().replace("’", "'").split())


def _script_query(
    user_text: str,
    category_key: str,
    classified_intent: str | None,
) -> str:
    parts = [user_text or "", category_key]
    if classified_intent:
        parts.append(classified_intent)
    return " ".join(part for part in parts if part).strip()


def _choose_category(
    *,
    user_text: str,
    state: _FunnelState,
    assistant_reply_count: int | None,
    user_level: str,
    classified_intent: str | None = None,
) -> tuple[str | None, str, str]:
    text_value = str(user_text or "").lower()
    minutes = state.minutes_since_link
    if classified_intent == "conversion.objection":
        return "app_download_objection", classified_intent, "download_objection"
    direct_link_request = _is_direct_link_request(text_value)
    if state.tracking_id:
        if state.downloaded or state.registered or state.paid:
            return None, "third_party_handoff", "download_complete"
        if _is_explicit_link_request(text_value):
            return "app_download_direct_cta", "app_download_direct_cta", "pre_click"
        if state.clicked and not state.downloaded and (minutes is None or minutes >= 3):
            return "app_link_clicked_followup", "app_link_clicked_followup", "clicked_not_downloaded"
        if not state.clicked and minutes is not None and minutes < 10:
            return None, "recent_link_exposed", "pre_click"

    if _has_any(text_value, ("scam", "fake", "safe", "real", "why download", "why app", "is this real")):
        return "trust_reassurance", "trust_reassurance", "trust"
    if _has_any(text_value, ("don't want to download", "dont want to download", "no download", "too much work", "not downloading", "不想下载", "不下载", "麻烦")):
        return "app_download_objection", "app_download_objection", "download_objection"
    if direct_link_request or _has_any(
        text_value,
        (
            "link",
            "app",
            "download",
            "where",
            "continue",
            "send it",
            "private",
            "privately",
            "more privately",
            "talk more",
            "where can i talk",
            "room",
            "platform",
            "链接",
            "下载",
            "继续",
            "哪里",
            "私聊",
        ),
    ):
        return "app_download_direct_cta", "app_download_direct_cta", "pre_click"

    count = assistant_reply_count or 0
    if user_level in {"A", "S"} and count >= 2:
        return "operator_app_conversion", "operator_app_conversion", "pre_click_high_value"
    if count >= 3:
        return "app_download_after_warmup", "app_download_after_warmup", "pre_click_warm"
    if count >= 1 and not state.tracking_id:
        return "app_download_first_push", "app_download_first_push", "pre_click_first"
    return None, "not_ready", "pre_click"


async def _audit_decision(
    *,
    db: Any,
    decision: AppDownloadDecision,
    conversation_id: str,
    trigger_message_id: str | None,
    user_text: str,
    trace_id: str,
) -> None:
    ctx = ScriptMatchContext(
        hook="reply",
        platform="telegram_real_user",
        user_level=decision.user_level,
        intent_id=decision.intent,
        user_text=user_text,
        script_match_stage=decision.scene_step,
        conversation_id=conversation_id,
        message_id=trigger_message_id,
        persona_slug=decision.persona_slug,
        category_key=decision.category_key,
        language="en",
        trace_id=trace_id,
        metadata={
            "source": "app_download_conversion",
            "scene_step": decision.scene_step,
        },
    )
    result = ScriptMatchResult(
        hook="reply",
        matched=True,
        script_ids=[decision.script_hit_id],
        degradation=None,
        script_hit_id=decision.script_hit_id,
        category_key=decision.category_key,
        content=decision.content,
    )
    await record_script_match_result(db=db, ctx=ctx, result=result)


def _render_script(content: str, *, app_download_url: str) -> str:
    return str(content).replace("{{app_download_url}}", app_download_url)


def _preferences(profile_row: dict[str, Any] | None) -> dict[str, Any]:
    if not profile_row:
        return {}
    prefs = profile_row.get("preferences") or {}
    return prefs if isinstance(prefs, dict) else {}


def _relationship_stage(profile_row: dict[str, Any] | None) -> str:
    if not profile_row:
        return "S0"
    return str(profile_row.get("relationship_stage") or "S0").strip().upper()


def _persona_slug(character_row: dict[str, Any] | None) -> str | None:
    if not character_row:
        return None
    value = character_row.get("persona_prompt_slug") or character_row.get("persona_slug")
    return str(value).strip() if value else None


def _reply_language(profile_row: dict[str, Any] | None, user_text: str) -> str:
    profile = profile_row or {}
    language = (
        profile.get("language")
        or _preferences(profile).get("language")
        or _preferences(profile).get("user_language")
    )
    if language:
        return normalize_language(str(language), default="en")
    return normalize_language(
        detect_language_from_text(str(user_text or ""), default="en"),
        default="en",
    )


def _has_any(text_value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text_value for needle in needles)


def _is_direct_link_request(text_value: str) -> bool:
    return _has_any(
        text_value,
        (
            "link",
            "app",
            "download",
            "quick sign up",
            "sign up",
            "where",
            "continue",
            "send it",
            "private",
            "privately",
            "more privately",
            "talk more",
            "where can i talk",
            "room",
            "platform",
            "链接",
            "下载",
            "继续",
            "哪里",
            "私聊",
            "閾炬帴",
            "涓嬭浇",
            "缁х画",
            "鍝噷",
            "绉佽亰",
        ),
    )


def _is_explicit_link_request(text_value: str) -> bool:
    return _has_any(
        text_value,
        (
            "link",
            "app link",
            "download app",
            "download link",
            "download",
            "quick sign up",
            "sign up",
            "send it",
            "send me",
            "链接",
            "下载",
            "閾炬帴",
            "涓嬭浇",
        ),
    )
