from __future__ import annotations

import contextvars
import re
from dataclasses import dataclass
from typing import Any

from loguru import logger
from sqlalchemy import text

from core.config import settings
from services.app_download_platforms import resolve_app_download_url
from services.emotion_lexicon import detect_language_from_text, normalize_language
from services.link_cooldown import (
    is_conversation_link_cooldown_active,
    is_within_link_cooldown,
)
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
    "nudes",
    "照片",
    "图片",
    "自拍",
    "裸体",
    "裸照",
    "大奶",
    "奶子",
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
    "视频",
    "小视频",
    "录像",
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
    "have",
    "got",
    "any",
    "do you have",
    "you have",
    "想",
    "想看",
    "想要",
    "要",
    "看",
    "发",
    "有",
    "有没有",
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

    from services.user_request_intent import (
        bypasses_link_cooldown,
        forces_app_download_script,
        is_serious_conversation_request,
        is_trust_reassurance_request,
    )

    force_link_script = forces_app_download_script(user_text)
    if await is_conversation_link_cooldown_active(db, conversation_id=conversation_id) and not bypasses_link_cooldown(user_text):
        logger.bind(
            component="app_download_conversion",
            trace_id=trace_id,
            conversation_id=conversation_id,
        ).info("app_download_conversion.link_cooldown_skip")
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

    if force_link_script:
        forced = await _build_forced_link_decision(
            db,
            user_text=user_text,
            destination_url=destination_url,
            profile=profile,
            character_row=character_row,
            conversation_id=conversation_id,
            trigger_message_id=trigger_message_id,
            trace_id=trace_id,
        )
        if forced is not None:
            return forced

    if is_trust_reassurance_request(user_text):
        trust = await _build_category_script_decision(
            db,
            user_text=user_text,
            category_key="trust_reassurance",
            scene_step="trust_priority",
            destination_url=destination_url,
            profile=profile,
            character_row=character_row,
            conversation_id=conversation_id,
            trigger_message_id=trigger_message_id,
            trace_id=trace_id,
            include_download_url=False,
        )
        if trust is not None:
            return trust

    if is_serious_conversation_request(user_text):
        serious = await _build_serious_conversation_decision(
            db,
            user_text=user_text,
            profile=profile,
            character_row=character_row,
            conversation_id=conversation_id,
            trigger_message_id=trigger_message_id,
            trace_id=trace_id,
        )
        if serious is not None:
            return serious

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
        is_t1 = country_tier(country_code) == "T1" if country_code else None
        content = _append_asset_download_copy(
            str(first_hit.get("content") or ""),
            app_download_url=destination_url,
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

    asset_triggers = await _match_whitelist_asset_fallback(
        db=db,
        user_text=user_text,
        user_level=user_level,
        persona_slug=_persona_slug(character_row),
        language=_reply_language(profile, user_text),
    )
    if asset_triggers:
        first_hit, matched_keyword = asset_triggers[0]
        assets: list[dict[str, Any]] = []
        for asset in await _load_script_assets(db=db, script_template_id=first_hit["id"]):
            assets.append(asset)
        is_t1 = country_tier(country_code) == "T1" if country_code else None
        decision = AppDownloadDecision(
            content=_append_asset_download_copy("", app_download_url=destination_url),
            category_key=str(first_hit.get("category_key") or "app_download_first_push"),
            script_hit_id=str(first_hit["id"]),
            assets=assets,
            user_level=user_level,
            persona_slug=first_hit.get("persona_slug") or _persona_slug(character_row),
            intent="asset_keyword_request",
            scene_step=f"asset_keyword:{matched_keyword}",
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
            matched_keyword=matched_keyword,
            asset_count=len(assets),
        ).info("app_download_conversion.asset_keyword_whitelist_fallback")
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
            SELECT id, asset_type, asset_url, storage_path, mime_type, caption, sort_order
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
        for keyword in _split_asset_keywords(str(data.get("content") or "")):
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


def _asset_kind_from_title(title: str) -> str | None:
    if "视频" in title or "video" in title.casefold():
        return "video"
    if "图片" in title or "photo" in title.casefold() or "image" in title.casefold():
        return "image"
    return None


def _detect_whitelist_asset_kind(user_text: str | None) -> str | None:
    from services.video_request_handoff import (
        is_live_video_call_request,
        is_prerecorded_video_file_request,
    )

    text_value = _normalize_keyword_text(user_text)
    if not text_value or is_live_video_call_request(text_value):
        return None
    if is_prerecorded_video_file_request(text_value):
        return "video"
    for keyword in ASSET_IMAGE_KEYWORDS:
        if _keyword_matches(text_value, keyword, asset_kind="image"):
            return "image"
    if _has_any(
        text_value,
        (
            "show me more",
            "see more of you",
            "want to see more",
            "something different",
            "private video",
            "想看更多",
            "再多发",
            "发更多",
        ),
    ):
        if _has_any(text_value, ("video", "videos", "vid", "clip", "视频", "录像")):
            return "video"
        return "image"
    return None


async def _match_whitelist_asset_fallback(
    *,
    db: Any,
    user_text: str,
    user_level: str,
    persona_slug: str | None,
    language: str,
) -> list[tuple[dict[str, Any], str]]:
    kind = _detect_whitelist_asset_kind(user_text)
    if not kind:
        return []
    title = ASSET_KEYWORD_TRIGGER_TITLES[0 if kind == "video" else 1]
    row = (
        await db.execute(
            text(
                """
                SELECT id, category_key, title, content, language, platform,
                       user_level, persona_slug, hook
                FROM script_templates
                WHERE status = 'approved'
                  AND title = :title
                  AND hook = 'reply'
                  AND (platform = 'telegram_real_user' OR platform IS NULL)
                  AND (user_level = :user_level OR user_level IS NULL)
                  AND (persona_slug = :persona_slug OR persona_slug IS NULL OR :persona_slug IS NULL)
                  AND language IN (:language, 'en')
                ORDER BY
                  CASE WHEN language = :language THEN 0 ELSE 1 END,
                  updated_at DESC,
                  created_at DESC
                LIMIT 1
                """
            ),
            {
                "title": title,
                "user_level": user_level,
                "persona_slug": persona_slug,
                "language": language or "en",
            },
        )
    ).first()
    if row is None:
        return []
    data = dict(row._mapping)
    matched_keyword = kind
    text_value = _normalize_keyword_text(user_text)
    keywords = ASSET_VIDEO_KEYWORDS if kind == "video" else ASSET_IMAGE_KEYWORDS
    for keyword in keywords:
        if _keyword_matches(text_value, keyword, asset_kind=kind):
            matched_keyword = keyword
            break
    return [(data, matched_keyword)]


async def _build_serious_conversation_decision(
    db: Any,
    *,
    user_text: str,
    profile: dict[str, Any],
    character_row: dict[str, Any] | None,
    conversation_id: str,
    trigger_message_id: str | None,
    trace_id: str,
) -> AppDownloadDecision:
    lang = _reply_language(profile, user_text)
    replies = {
        "en": "Got it — no games. What's really on your mind?",
        "zh": "好，我们认真聊。你想聊什么？",
        "es": "Entendido — sin juegos. ¿Qué tienes en mente?",
        "pt": "Entendi — sem joguinhos. O que você quer falar de verdade?",
        "fr": "Compris — pas de blagues. Qu'est-ce qui te préoccupe vraiment?",
    }
    content = replies.get(lang, replies["en"])
    user_level = str(profile.get("user_level") or "C").upper()
    country_code = normalize_country_code(
        profile.get("country_code") or _preferences(profile).get("country_code")
    )
    age = age_from_preferences(_preferences(profile))
    is_t1 = country_tier(country_code) == "T1" if country_code else None
    decision = AppDownloadDecision(
        content=content,
        category_key="trust_reassurance",
        script_hit_id="serious-conversation-fallback",
        assets=[],
        user_level=user_level,
        persona_slug=_persona_slug(character_row),
        intent="serious_conversation",
        scene_step="serious_priority",
        country_code=country_code,
        age=age,
        is_t1_country=is_t1,
        language=lang,
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
    return decision


async def _build_category_script_decision(
    db: Any,
    *,
    user_text: str,
    category_key: str,
    scene_step: str,
    destination_url: str,
    profile: dict[str, Any],
    character_row: dict[str, Any] | None,
    conversation_id: str,
    trigger_message_id: str | None,
    trace_id: str,
    include_download_url: bool = True,
) -> AppDownloadDecision | None:
    user_level = str(profile.get("user_level") or "C").upper()
    country_code = normalize_country_code(
        profile.get("country_code") or _preferences(profile).get("country_code")
    )
    age = age_from_preferences(_preferences(profile))
    persona_slug = _persona_slug(character_row)
    result = await search_script_templates(
        db=db,
        query=ScriptTemplateQuery(
            query=_script_query(user_text, category_key, None),
            platform="telegram_real_user",
            user_level=user_level,
            persona_slug=persona_slug,
            hook="reply",
            category_key=category_key,
            language=_reply_language(profile, user_text),
            limit=1,
        ),
        trace_id=trace_id,
    )
    if result.hits:
        hit = result.hits[0]
        raw = hit.content.replace("{{app_download_url}}", "").strip()
        if include_download_url:
            content = _compact_app_link_reply(
                _render_script(hit.content, app_download_url=destination_url, force_url=False),
                destination_url=destination_url,
            )
        else:
            from services.link_cooldown import strip_links_from_reply

            content = strip_links_from_reply(raw)
            content = re.sub(r"\s*\(code:\s*c5a8we\)", "", content, flags=re.IGNORECASE).strip()
            content = re.sub(r"\s*tap here now:?\s*$", "", content, flags=re.IGNORECASE).strip()
        script_hit_id = str(hit.id)
        resolved_persona = hit.persona_slug or persona_slug
    else:
        if category_key == "trust_reassurance":
            content = "I'm 100% real — just a girl on her phone, not a bot."
        else:
            return None
        script_hit_id = f"{category_key}-fallback"
        resolved_persona = persona_slug
    is_t1 = country_tier(country_code) == "T1" if country_code else None
    decision = AppDownloadDecision(
        content=content.strip(),
        category_key=category_key,
        script_hit_id=script_hit_id,
        assets=[],
        user_level=user_level,
        persona_slug=resolved_persona,
        intent=category_key,
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
    return decision


async def _build_forced_link_decision(
    db: Any,
    *,
    user_text: str,
    destination_url: str,
    profile: dict[str, Any],
    character_row: dict[str, Any] | None,
    conversation_id: str,
    trigger_message_id: str | None,
    trace_id: str,
) -> AppDownloadDecision | None:
    from services.user_request_intent import is_broken_link_report

    user_level = str(profile.get("user_level") or "C").upper()
    country_code = normalize_country_code(
        profile.get("country_code") or _preferences(profile).get("country_code")
    )
    age = age_from_preferences(_preferences(profile))
    persona_slug = _persona_slug(character_row)
    category_key = "app_download_direct_cta"
    scene_step = "app_link_broken_retry" if is_broken_link_report(user_text) else "pre_click_forced"
    result = await search_script_templates(
        db=db,
        query=ScriptTemplateQuery(
            query=_script_query(user_text, category_key, None),
            platform="telegram_real_user",
            user_level=user_level,
            persona_slug=persona_slug,
            hook="reply",
            category_key=category_key,
            language=_reply_language(profile, user_text),
            limit=1,
        ),
        trace_id=trace_id,
    )
    if result.hits:
        hit = result.hits[0]
        content = _compact_app_link_reply(
            _render_script(
                hit.content,
                app_download_url=destination_url,
                force_url=False,
            ),
            destination_url=destination_url,
        )
        script_hit_id = str(hit.id)
        resolved_persona = hit.persona_slug or persona_slug
    else:
        content = _compact_app_link_reply("", destination_url=destination_url)
        script_hit_id = "forced-link-fallback"
        resolved_persona = persona_slug
    is_t1 = country_tier(country_code) == "T1" if country_code else None
    decision = AppDownloadDecision(
        content=content,
        category_key=category_key,
        script_hit_id=script_hit_id,
        assets=[],
        user_level=user_level,
        persona_slug=resolved_persona,
        intent="app_download_direct_cta",
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
        category_key=category_key,
        scene_step=scene_step,
    ).info("app_download_conversion.forced_link_script")
    return decision


def _keyword_matches(normalized_text: str, keyword: str, *, asset_kind: str | None = None) -> bool:
    key = _normalize_keyword_text(keyword)
    if not key or key in ASSET_BLOCKED_KEYWORDS:
        return False

    allowed_keywords = _allowed_asset_keywords(asset_kind)
    if key not in allowed_keywords:
        return False
    if key not in normalized_text:
        return False
    if normalized_text == key:
        if asset_kind == "video" and key in {"video", "vid"}:
            return False
        return True
    if _has_asset_request_intent(normalized_text):
        return True
    return len(key.split()) > 1 and _starts_with_request_term(key)


def _allowed_asset_keywords(asset_kind: str | None) -> set[str]:
    if asset_kind == "image":
        return {_normalize_keyword_text(value) for value in ASSET_IMAGE_KEYWORDS}
    if asset_kind == "video":
        return {_normalize_keyword_text(value) for value in ASSET_VIDEO_KEYWORDS}
    return {
        _normalize_keyword_text(value)
        for value in (*ASSET_IMAGE_KEYWORDS, *ASSET_VIDEO_KEYWORDS)
    }


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
    if _is_broken_link_report(text_value):
        return "app_download_direct_cta", "app_download_direct_cta", "app_link_broken_retry"
    persona_location_question = _is_persona_location_question(text_value)
    direct_link_request = _is_direct_link_request(text_value)
    if state.tracking_id:
        if _is_explicit_link_request(text_value):
            return "app_download_direct_cta", "app_download_direct_cta", "pre_click"
        if state.downloaded or state.registered or state.paid:
            return None, "third_party_handoff", "download_complete"
        if is_within_link_cooldown(minutes):
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
    if _has_any(
        text_value,
        (
            "what are you doing",
            "what're you doing",
            "how are you",
            "what's up",
            "whats up",
            "wyd",
            "how r u",
            "how are u",
            "在干嘛",
            "干什么",
            "忙什么",
        ),
    ):
        return None, "smalltalk", "pre_click"
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


def _render_script(content: str, *, app_download_url: str, force_url: bool = False) -> str:
    rendered = str(content).replace("{{app_download_url}}", app_download_url)
    if force_url and app_download_url and app_download_url not in rendered:
        return _compact_app_link_reply(rendered, destination_url=app_download_url)
    return rendered


def _compact_app_link_reply(content: str, *, destination_url: str) -> str:
    """One clean link line — avoids duplicate URLs and stray destination fragments."""
    url = str(destination_url or "").strip()
    if not url:
        return str(content or "").strip()
    body = str(content or "").strip()
    if body and url in body and body.lower().count("http") <= 1:
        return body
    return f"TAP HERE — private room unlocked: {url} (code: c5a8we)"


def _append_asset_download_copy(content: str, *, app_download_url: str) -> str:
    body = str(content or "").strip()
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


def _is_broken_link_report(text_value: str) -> bool:
    from services.user_request_intent import is_broken_link_report

    return is_broken_link_report(text_value)


def _is_explicit_link_request(text_value: str) -> bool:
    from services.user_request_intent import is_explicit_app_link_request

    if is_explicit_app_link_request(text_value):
        return True
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
        ),
    )
