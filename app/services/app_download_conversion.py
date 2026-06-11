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
SCRIPT_REPLY_SKIP_LLM_CATEGORIES: frozenset[str] = frozenset(
    {
        "app_download_first_push",
        "app_download_direct_cta",
        "app_download_after_warmup",
    }
)
SCRIPT_REPLY_SKIP_LLM_INTENTS: frozenset[str] = frozenset({"asset_keyword_request"})
ASSET_KEYWORD_TRIGGER_TITLES: tuple[str, ...] = (
    "用户聊天中想要看本人视频的关键词",
    "用户聊天中想要看本人图片的关键词",
)
ASSET_KEYWORD_APP_DOWNLOAD_COPY = (
    "Sent! 😉 That's just my casual look text-blocked by TG. I actually just uploaded "
    "a super wild bedroom video on my private secure app. Check my room L8385160 "
    "right now before I take it down."
)
ASSET_KEYWORD_APP_DOWNLOAD_COPY = (
    "TG blocks all my unedited premium content anyway. Move over to my private "
    "chatroom, everything is unlocked there:"
)
ASSET_IMAGE_KEYWORDS: tuple[str, ...] = (
    "photo",
    "photos",
    "pic",
    "pics",
    "picture",
    "pictures",
    "selfie",
    "selfies",
    "image",
    "images",
    "snapshot",
    "snap",
    "face",
    "body",
    "face pic",
    "body pic",
    "full body",
    "mirror selfie",
    "your face",
    "your body",
    "照片",
    "图片",
    "自拍",
)
ASSET_VIDEO_KEYWORDS: tuple[str, ...] = (
    "video",
    "videos",
    "vid",
    "vids",
    "clip",
    "clips",
    "movie",
    "gif",
    "tape",
    "recording",
    "custom video",
    "dirty video",
    "short clip",
    "private video",
    "bedroom video",
    "cam",
    "webcam",
    "video call",
    "facetime",
    "live",
    "live show",
    "private call",
    "视频",
    "影片",
    "录像",
    "小视频",
    "露脸视频",
)
ASSET_REQUEST_TERMS: tuple[str, ...] = (
    "send",
    "show",
    "see",
    "watch",
    "look",
    "view",
    "share",
    "drop",
    "give",
    "upload",
    "want",
    "wanna",
    "need",
    "can i",
    "could i",
    "may i",
    "let me",
    "lemme",
    "please",
    "pls",
    "想",
    "想看",
    "想要",
    "要",
    "看",
    "发",
    "发来",
    "发送",
    "给我",
    "来个",
    "能不能",
    "可以",
    "有",
    "有没有",
    "能发",
    "可以发",
    "想看下",
    "看看",
)
ASSET_BLOCKED_KEYWORDS: tuple[str, ...] = (
    "cock",
    "dick",
    "fuck",
    "sexy",
    "horny",
    "hard",
    "nipples",
    "nipple",
    "tits",
    "boobs",
    "breasts",
    "pussy",
    "clit",
    "ass",
    "booty",
    "squirt",
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
    language: str | None = None


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


def conversion_decision_skips_llm(decision: AppDownloadDecision | None) -> bool:
    """Return True when the approved script body should be sent verbatim (no LLM)."""
    if decision is None:
        return False
    if decision.intent in SCRIPT_REPLY_SKIP_LLM_INTENTS:
        return True
    return decision.category_key in SCRIPT_REPLY_SKIP_LLM_CATEGORIES


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

    asset_triggers = await _match_asset_keyword_triggers(
        db=db,
        user_text=user_text,
        user_level=user_level,
        persona_slug=_persona_slug(character_row),
        language=_reply_language(profile, user_text),
    )
    if asset_triggers:
        first_hit, _ = asset_triggers[0]
        matched_keywords: list[str] = []
        assets: list[dict[str, Any]] = []
        seen_asset_ids: set[str] = set()
        for hit, matched_keyword in asset_triggers:
            matched_keywords.append(matched_keyword)
            for asset in await _load_script_assets(db=db, script_template_id=hit["id"]):
                asset_key = str(asset.get("id") or asset.get("asset_url") or "")
                if asset_key and asset_key in seen_asset_ids:
                    continue
                if asset_key:
                    seen_asset_ids.add(asset_key)
                assets.append(asset)
        if matched_keywords:
            is_t1 = country_tier(country_code) == "T1" if country_code else None
            content = _build_asset_keyword_reply_text(
                app_download_url=destination_url,
                assets=_sort_assets_for_delivery(assets),
            )
            decision = AppDownloadDecision(
                content=content,
                category_key=str(first_hit.get("category_key") or "app_download_first_push"),
                script_hit_id=str(first_hit["id"]),
                assets=assets,
                user_level=user_level,
                persona_slug=first_hit.get("persona_slug") or _persona_slug(character_row),
                intent="asset_keyword_request",
                scene_step=f"asset_keyword:{','.join(matched_keywords[:4])}",
                country_code=country_code,
                age=age,
                is_t1_country=is_t1,
                language=_reply_language(profile, user_text),
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
                matched_keyword=",".join(matched_keywords),
                asset_count=len(assets),
            ).info("app_download_conversion.asset_keyword_selected")
            return decision

    if user_level == "D":
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
        force_url=_category_requires_download_url(hit.category_key),
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
        language=_reply_language(profile, user_text),
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


async def _match_asset_keyword_triggers(
    *,
    db: Any,
    user_text: str,
    user_level: str,
    persona_slug: str | None,
    language: str,
) -> list[tuple[dict[str, Any], str]]:
    text_value = _normalize_keyword_text(user_text)
    if not text_value:
        return []
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
    matches: list[tuple[dict[str, Any], str]] = []
    seen_template_ids: set[str] = set()
    for row in result.fetchall():
        data = dict(row._mapping)
        template_id = str(data.get("id") or "")
        if template_id in seen_template_ids:
            continue
        asset_kind = _asset_kind_from_title(str(data.get("title") or ""))
        template_keywords = _split_asset_keywords(str(data.get("content") or ""))
        for keyword in _merge_asset_keywords(template_keywords, asset_kind):
            if _keyword_matches(text_value, keyword, asset_kind=asset_kind):
                matches.append((data, keyword))
                if template_id:
                    seen_template_ids.add(template_id)
                break
    return matches


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


def _merge_asset_keywords(
    template_keywords: list[str],
    asset_kind: str | None,
) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for keyword in [*template_keywords, *_builtin_keywords_for_asset_kind(asset_kind)]:
        key = _normalize_keyword_text(keyword)
        if not key or key in seen:
            continue
        merged.append(keyword)
        seen.add(key)
    return merged


def _builtin_keywords_for_asset_kind(asset_kind: str | None) -> tuple[str, ...]:
    if asset_kind == "video":
        return ASSET_VIDEO_KEYWORDS
    if asset_kind == "image":
        return ASSET_IMAGE_KEYWORDS
    return ()


def _asset_kind_from_title(title: str) -> str | None:
    if "视频" in title or "video" in title.casefold():
        return "video"
    if "图片" in title or "photo" in title.casefold() or "image" in title.casefold():
        return "image"
    return None


def _keyword_matches(normalized_text: str, keyword: str, *, asset_kind: str | None = None) -> bool:
    key = _normalize_keyword_text(keyword)
    if not key or key in ASSET_BLOCKED_KEYWORDS:
        return False
    if key not in normalized_text:
        return False
    if normalized_text == key:
        return True
    if _has_asset_request_intent(normalized_text):
        return True
    if asset_kind and _is_media_noun_keyword(key, asset_kind):
        if normalized_text.endswith(("吗", "?", "嘛", "么")):
            return True
        if len(normalized_text) <= 6:
            return True
    return len(key.split()) > 1 and _starts_with_request_term(key)


def _is_media_noun_keyword(key: str, asset_kind: str) -> bool:
    if asset_kind == "video":
        return key in {"视频", "影片", "录像", "小视频", "video", "videos", "vid", "clip", "clips"}
    if asset_kind == "image":
        return key in {
            "照片", "图片", "自拍", "photo", "photos", "pic", "pics", "picture", "pictures", "selfie", "nudes",
        }
    return False


def _has_asset_request_intent(normalized_text: str) -> bool:
    return any(term in normalized_text for term in ASSET_REQUEST_TERMS)


def _starts_with_request_term(normalized_text: str) -> bool:
    return any(
        normalized_text == term or normalized_text.startswith(f"{term} ")
        for term in ASSET_REQUEST_TERMS
    )


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
    persona_location_question = _is_persona_location_question(text_value)
    direct_link_request = _is_direct_link_request(text_value)
    if state.tracking_id:
        if state.downloaded or state.registered or state.paid:
            return None, "third_party_handoff", "download_complete"
        if state.clicked and not state.downloaded:
            if _is_explicit_link_request(text_value):
                return "app_download_direct_cta", "app_download_direct_cta", "pre_click"
            return None, "clicked_pending_download", "post_click_worker"
        if _is_explicit_link_request(text_value):
            return "app_download_direct_cta", "app_download_direct_cta", "pre_click"
        if not state.clicked and minutes is not None and minutes < 10:
            return None, "recent_link_exposed", "pre_click"

    if _has_any(text_value, ("scam", "fake", "safe", "real", "why download", "why app", "is this real")):
        return "trust_reassurance", "trust_reassurance", "trust"
    if _has_any(text_value, ("don't want to download", "dont want to download", "no download", "too much work", "not downloading", "不想下载", "不下载", "麻烦")):
        return "app_download_objection", "app_download_objection", "download_objection"
    if not persona_location_question and (direct_link_request or _has_any(
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
    )):
        return "app_download_direct_cta", "app_download_direct_cta", "pre_click"

    count = assistant_reply_count or 0
    if user_level in {"A", "S"} and count >= 2:
        return "operator_app_conversion", "operator_app_conversion", "pre_click_high_value"
    if count >= 3:
        return "app_download_after_warmup", "app_download_after_warmup", "pre_click_warm"
    if not state.tracking_id:
        if count >= 1:
            return "app_download_first_push", "app_download_first_push", "pre_click_first"
        if count == 0 and user_level in {"B", "C"}:
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


def _render_script(content: str, *, app_download_url: str, force_url: bool = False) -> str:
    rendered = str(content).replace("{{app_download_url}}", app_download_url)
    if force_url and app_download_url and app_download_url not in rendered:
        return f"{rendered.rstrip()}\n{app_download_url}"
    return rendered


_ASSET_DELIVERY_ORDER = {"image": 0, "video": 1, "voice": 2, "audio": 3}


def _sort_assets_for_delivery(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        assets,
        key=lambda asset: (
            _ASSET_DELIVERY_ORDER.get(str(asset.get("asset_type") or "").lower(), 9),
            int(asset.get("sort_order") or 0),
        ),
    )


def _build_asset_keyword_reply_text(
    *,
    app_download_url: str,
    assets: list[dict[str, Any]],
) -> str:
    """Reply copy for keyword hits; template content holds triggers, not outgoing text."""
    caption_parts = [
        str(asset.get("caption") or "").strip()
        for asset in assets
        if str(asset.get("caption") or "").strip()
    ]
    body = caption_parts[0] if caption_parts else ""
    cta = f"{ASSET_KEYWORD_APP_DOWNLOAD_COPY} {app_download_url} (Code: c5a8we)".strip()
    if not body:
        return cta
    if app_download_url and app_download_url in body:
        return body
    return f"{body.rstrip()}\n\n{cta}"


def _category_requires_download_url(category_key: str | None) -> bool:
    return str(category_key or "") in APP_DOWNLOAD_CATEGORIES


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


def _is_persona_location_question(text_value: str) -> bool:
    value = " ".join(str(text_value or "").casefold().split())
    if not value:
        return False
    return _has_any(
        value,
        (
            "where do you live",
            "where are you from",
            "where r u from",
            "where you from",
            "where do u live",
            "where u live",
            "where are u from",
            "你来自哪里",
            "你來自哪裡",
            "你住哪里",
            "你住哪裡",
            "你在哪里",
            "你在哪裡",
            "你在哪",
            "来自哪里",
            "來自哪裡",
            "住哪里",
            "住哪裡",
            "在哪里",
            "在哪裡",
        ),
    )


def _is_direct_link_request(text_value: str) -> bool:
    if _is_persona_location_question(text_value):
        return False
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
