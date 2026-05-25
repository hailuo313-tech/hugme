from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import Any

from loguru import logger
from sqlalchemy import text

from core.config import settings
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
) -> AppDownloadDecision | None:
    """Return an approved App-download conversion script when the funnel calls for it.

    The selector is deliberately conservative: missing App URL, incomplete profile,
    S5 recovery, recent unclicked links, or no matching approved template all fall
    through to the existing LLM path.
    """
    clear_last_app_download_decision()
    destination_url = str(settings.APP_DOWNLOAD_URL or "").strip()
    if not settings.APP_DOWNLOAD_CONVERSION_ENABLED or not destination_url:
        return None
    if db is None or profile_row is None:
        return None
    if _relationship_stage(profile_row) == "S5":
        return None

    user_level = str(profile_row.get("user_level") or "C").upper()
    country_code = normalize_country_code(
        profile_row.get("country_code")
        or _preferences(profile_row).get("country_code")
    )
    age = age_from_preferences(_preferences(profile_row))
    if user_level == "D" or not country_code or age is None:
        return None

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
    )
    if category_key is None:
        return None

    persona_slug = _persona_slug(character_row)
    result = await search_script_templates(
        db=db,
        query=ScriptTemplateQuery(
            query=user_text or category_key,
            platform="telegram_real_user",
            user_level=user_level,
            persona_slug=persona_slug,
            hook="reply",
            category_key=category_key,
            language=_reply_language(profile_row, user_text),
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


def _choose_category(
    *,
    user_text: str,
    state: _FunnelState,
    assistant_reply_count: int | None,
    user_level: str,
) -> tuple[str | None, str, str]:
    text_value = str(user_text or "").lower()
    minutes = state.minutes_since_link
    if state.tracking_id:
        if state.downloaded or state.registered or state.paid:
            return None, "third_party_handoff", "download_complete"
        if state.clicked and not state.downloaded and (minutes is None or minutes >= 3):
            return "app_link_clicked_followup", "app_link_clicked_followup", "clicked_not_downloaded"
        if not state.clicked and minutes is not None and minutes < 10:
            return None, "recent_link_exposed", "pre_click"

    if _has_any(text_value, ("scam", "fake", "safe", "real", "why download", "why app", "is this real")):
        return "trust_reassurance", "trust_reassurance", "trust"
    if _has_any(text_value, ("don't want to download", "dont want to download", "no download", "too much work", "not downloading", "不想下载", "不下载", "麻烦")):
        return "app_download_objection", "app_download_objection", "download_objection"
    if _has_any(text_value, ("link", "app", "download", "where", "continue", "send it", "链接", "下载", "继续", "哪里")):
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


def _preferences(profile_row: dict[str, Any]) -> dict[str, Any]:
    prefs = profile_row.get("preferences") or {}
    return prefs if isinstance(prefs, dict) else {}


def _relationship_stage(profile_row: dict[str, Any]) -> str:
    return str(profile_row.get("relationship_stage") or "S0").strip().upper()


def _persona_slug(character_row: dict[str, Any] | None) -> str | None:
    if not character_row:
        return None
    value = character_row.get("persona_prompt_slug") or character_row.get("persona_slug")
    return str(value).strip() if value else None


def _reply_language(profile_row: dict[str, Any], user_text: str) -> str:
    language = (
        profile_row.get("language")
        or _preferences(profile_row).get("language")
        or _preferences(profile_row).get("user_language")
    )
    if language:
        return "zh" if str(language).lower().startswith("zh") else "en"
    return "zh" if any("\u4e00" <= ch <= "\u9fff" for ch in str(user_text or "")) else "en"


def _has_any(text_value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text_value for needle in needles)
