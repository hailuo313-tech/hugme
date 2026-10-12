"""Send named 话术库 templates after inbound video calls.

Titles (exact match in ``script_templates.title``):
- 视频后发过去的信息01 — once after two successful auto-answers
- 视频后发过去的信息02 — 5 seconds after 01
- 视频后发过去的信息03 — on every inbound call from the 3rd valid call onward
  (skipped while a human owns the thread or has already replied)

Stop 03 (and all further auto-replies for that user) when they reply with
「已经注册」(AI semantic match) or send a screenshot/photo.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from services.human_takeover_gate import HUMAN_CONTROL_STATES
from services.link_attribution import render_tracking_links_as_html_cta, wrap_text_links_with_tracking
from services.mtproto.peer_resolve import resolve_telethon_peer
from services.outbound_account_gate import check_outbound_account
from services.script_asset_delivery import send_mtproto_asset
from services.telegram_account_manager import telegram_account_manager

RULE_01 = "视频后发过去的信息01"
RULE_02 = "视频后发过去的信息02"
RULE_03 = "视频后发过去的信息03"
POST_VIDEO_FIXED_NAME_PREFIX = "视频后发过去的信息"
POST_VIDEO_FIXED_02_DELAY_SECONDS = 5
POST_VIDEO_FIXED_03_DEBOUNCE_SECONDS = 30


def should_skip_post_video_auto_send(
    *,
    conversation_state: str | None,
    operator_replied: Any = False,
) -> bool:
    """Skip 01/02/03 once a human owns the thread or has already replied."""
    if operator_replied:
        return True
    return str(conversation_state or "") in HUMAN_CONTROL_STATES

_REGISTERED_RE = re.compile(
    r"(已经注册|已注册|already\s+registered|i(?:'ve| have)?\s+registered|signed\s+up\s+already)",
    re.IGNORECASE,
)
REGISTERED_INTENT_MODEL_NAME = "user_intent:already_registered"
_REGISTERED_CONFIDENCE_MIN = 0.55
_PLACEHOLDER_REPLY_RE = re.compile(r"^\[(photo|voice|emoji|sticker|image)\]$", re.IGNORECASE)

_REGISTERED_CLASSIFY_SYSTEM = """You decide if a user message means they already registered / signed up / created an account for this dating app.

Return JSON only:
{"already_registered": true, "confidence": 0.0, "reason": "short"}

already_registered=true when the MEANING is any of:
- already registered / signed up / created an account / I have an account
- 已经注册 / 已注册 / 注册过了 / 我有账号了 / 报名过了
- ya me registré / ya tengo cuenta / já me cadastrei / já tenho conta
- informal: done, I did it, finished, account is ready — ONLY if clearly about completing signup/registration

already_registered=false when:
- asking how to register, or saying they will register later
- yes/ok/done about something else (video, photo, age, city)
- registering a car, school, Telegram, email, or any other product
- screenshot/photo placeholders
- unclear or unrelated text

Use confidence >= 0.8 for clear statements, 0.55-0.8 if informal but likely, below 0.55 if unsure (then set already_registered false)."""

ChatFn = Callable[..., Awaitable[Any]]

_SCHEMA_SQL = [
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS post_video_fixed_01_sent_at TIMESTAMPTZ NULL",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS post_video_fixed_02_sent_at TIMESTAMPTZ NULL",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS post_video_fixed_03_last_sent_at TIMESTAMPTZ NULL",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS post_video_fixed_03_stopped_at TIMESTAMPTZ NULL",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS post_video_fixed_03_stop_reason TEXT NULL",
]

_schema_ready = False


def is_post_video_fixed_rule_name(name: str | None) -> bool:
    return str(name or "").strip().startswith(POST_VIDEO_FIXED_NAME_PREFIX)


def looks_like_registered_reply(text_value: str | None) -> bool:
    return bool(_REGISTERED_RE.search(str(text_value or "")))


def _extract_json_object(payload: str) -> dict[str, Any]:
    text_value = str(payload or "").strip()
    if not text_value:
        return {}
    if text_value.startswith("```"):
        text_value = text_value.strip("`")
        if text_value.lower().startswith("json"):
            text_value = text_value[4:].strip()
    try:
        data = json.loads(text_value)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        start = text_value.find("{")
        end = text_value.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text_value[start : end + 1])
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}


def parse_already_registered_payload(payload: str | dict[str, Any]) -> bool:
    data = payload if isinstance(payload, dict) else _extract_json_object(str(payload or ""))
    flag = data.get("already_registered")
    if flag is True:
        pass
    elif str(flag).strip().lower() in {"true", "yes", "1"}:
        flag = True
    else:
        return False
    raw_confidence = data.get("confidence")
    if raw_confidence is None:
        return True
    try:
        return float(raw_confidence) >= _REGISTERED_CONFIDENCE_MIN
    except (TypeError, ValueError):
        return True


def _should_classify_registered_text(text_value: str | None) -> bool:
    cleaned = str(text_value or "").strip()
    if not cleaned or _PLACEHOLDER_REPLY_RE.match(cleaned):
        return False
    return True


async def classify_already_registered_reply(
    text_value: str | None,
    *,
    trace_id: str | None = None,
    chat_fn: ChatFn | None = None,
) -> bool:
    """True when aux LLM says the user already registered/signed up."""
    if not _should_classify_registered_text(text_value):
        return False
    try:
        llm_chat = chat_fn
        if llm_chat is None:
            from services.llm import chat as llm_chat
        result = await llm_chat(
            messages=[
                {"role": "system", "content": _REGISTERED_CLASSIFY_SYSTEM},
                {"role": "user", "content": str(text_value)[:800]},
            ],
            trace_id=trace_id or "registered-intent",
            temperature=0.0,
            max_tokens=80,
            purpose="aux",
        )
    except Exception as exc:
        logger.bind(error_type=type(exc).__name__, trace_id=trace_id).warning(
            "post_inbound_video_fixed.registered_classify_failed"
        )
        return looks_like_registered_reply(text_value)
    if getattr(result, "error", None):
        logger.bind(trace_id=trace_id, error=str(result.error)).warning(
            "post_inbound_video_fixed.registered_classify_llm_error"
        )
        return looks_like_registered_reply(text_value)
    matched = parse_already_registered_payload(str(getattr(result, "content", "") or ""))
    logger.bind(
        trace_id=trace_id,
        matched=matched,
        preview=str(text_value or "")[:80],
    ).info("post_inbound_video_fixed.registered_classified")
    return matched


def _in_post_video_funnel(state: dict[str, Any] | None) -> bool:
    if not state:
        return False
    return bool(
        state.get("post_video_fixed_01_sent_at")
        or state.get("post_video_fixed_02_sent_at")
        or state.get("post_video_fixed_03_last_sent_at")
    )


def is_inbound_screenshot(message: Any) -> bool:
    """True for a photo or an image file (screenshot), not stickers."""
    if message is None:
        return False
    if getattr(message, "sticker", None):
        return False
    if getattr(message, "photo", None):
        return True
    document = getattr(message, "document", None)
    mime = str(getattr(document, "mime_type", None) or getattr(message, "mime_type", None) or "").lower()
    if mime.startswith("image/") and mime not in {"image/webp", "application/x-tgsticker"}:
        return True
    if document is not None:
        for attr in getattr(document, "attributes", None) or []:
            if "ImageSize" in type(attr).__name__:
                return True
    media = getattr(message, "media", None)
    media_name = type(media).__name__.lower() if media is not None else ""
    return "photo" in media_name and "sticker" not in media_name


async def ensure_post_video_fixed_columns(db: AsyncSession) -> None:
    global _schema_ready
    if _schema_ready:
        return
    existing = (
        await db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'conversations'
                  AND column_name IN (
                    'post_video_fixed_01_sent_at',
                    'post_video_fixed_02_sent_at',
                    'post_video_fixed_03_last_sent_at',
                    'post_video_fixed_03_stopped_at',
                    'post_video_fixed_03_stop_reason'
                  )
                """
            )
        )
    ).scalar_one()
    if int(existing or 0) >= len(_SCHEMA_SQL):
        _schema_ready = True
        return
    await db.execute(text("SET LOCAL lock_timeout = '2s'"))
    for stmt in _SCHEMA_SQL:
        await db.execute(text(stmt))
    await db.commit()
    _schema_ready = True


async def _conversation_state(
    db: AsyncSession,
    *,
    conversation_id: str | None,
    external_user_id: str | None,
) -> dict[str, Any] | None:
    if conversation_id:
        row = (
            await db.execute(
                text(
                    """
                    SELECT id::text,
                           state,
                           post_video_fixed_01_sent_at,
                           post_video_fixed_02_sent_at,
                           post_video_fixed_03_last_sent_at,
                           post_video_fixed_03_stopped_at,
                           EXISTS (
                             SELECT 1
                               FROM messages m
                              WHERE m.conversation_id = conversations.id
                                AND (
                                  m.sender_type = 'operator'
                                  OR COALESCE(m.is_operator_message, false) = true
                                )
                           ) AS operator_replied
                      FROM conversations
                     WHERE id = CAST(:cid AS uuid)
                     LIMIT 1
                    """
                ),
                {"cid": conversation_id},
            )
        ).mappings().first()
        if row:
            return dict(row)
    if not external_user_id:
        return None
    row = (
        await db.execute(
            text(
                """
                SELECT c.id::text,
                       c.state,
                       c.post_video_fixed_01_sent_at,
                       c.post_video_fixed_02_sent_at,
                       c.post_video_fixed_03_last_sent_at,
                       c.post_video_fixed_03_stopped_at,
                       EXISTS (
                         SELECT 1
                           FROM messages m
                          WHERE m.conversation_id = c.id
                            AND (
                              m.sender_type = 'operator'
                              OR COALESCE(m.is_operator_message, false) = true
                            )
                       ) AS operator_replied
                  FROM conversations c
                  JOIN users u ON u.id = c.user_id
                 WHERE u.external_id = :external_id
                 ORDER BY COALESCE(c.last_message_at, c.updated_at, c.created_at) DESC
                 LIMIT 1
                """
            ),
            {"external_id": external_user_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def _ensure_conversation_for_chat(
    db: AsyncSession,
    *,
    chat_id: int,
    conversation_id: str | None,
    external_user_id: str | None,
) -> dict[str, Any] | None:
    ext = external_user_id or f"tg_{int(chat_id)}"
    state = await _conversation_state(
        db,
        conversation_id=conversation_id,
        external_user_id=ext,
    )
    if state:
        return state
    user_id = str(uuid.uuid4())
    conv_id = str(uuid.uuid4())
    await db.execute(
        text(
            """
            INSERT INTO users (id, channel, external_id, status, created_at, updated_at)
            VALUES (CAST(:user_id AS uuid), 'telegram_real_user', :external_id, 'active', NOW(), NOW())
            ON CONFLICT (channel, external_id) DO UPDATE SET updated_at = NOW()
            RETURNING id
            """
        ),
        {"user_id": user_id, "external_id": ext},
    )
    user_row = (
        await db.execute(
            text("SELECT id FROM users WHERE channel='telegram_real_user' AND external_id=:external_id"),
            {"external_id": ext},
        )
    ).first()
    if not user_row:
        return None
    real_user_id = str(user_row[0])
    await db.execute(
        text(
            """
            INSERT INTO conversations (id, user_id, channel, state, last_message_at)
            VALUES (CAST(:cid AS uuid), CAST(:uid AS uuid), 'telegram_real_user', 'AI_ACTIVE', NOW())
            """
        ),
        {"cid": conv_id, "uid": real_user_id},
    )
    await db.commit()
    return await _conversation_state(db, conversation_id=conv_id, external_user_id=ext)


async def is_post_video_fixed_03_stopped(
    db: AsyncSession,
    *,
    conversation_id: str | None = None,
    external_user_id: str | None = None,
) -> bool:
    await ensure_post_video_fixed_columns(db)
    state = await _conversation_state(
        db,
        conversation_id=conversation_id,
        external_user_id=external_user_id,
    )
    return bool(state and state.get("post_video_fixed_03_stopped_at"))


async def mark_post_video_fixed_03_stopped(
    db: AsyncSession,
    *,
    conversation_id: str,
    reason: str,
) -> bool:
    await ensure_post_video_fixed_columns(db)
    result = await db.execute(
        text(
            """
            UPDATE conversations
               SET post_video_fixed_03_stopped_at = COALESCE(post_video_fixed_03_stopped_at, NOW()),
                   post_video_fixed_03_stop_reason = COALESCE(post_video_fixed_03_stop_reason, :reason),
                   updated_at = NOW()
             WHERE id = CAST(:cid AS uuid)
               AND post_video_fixed_03_stopped_at IS NULL
            """
        ),
        {"cid": conversation_id, "reason": reason[:80]},
    )
    await db.commit()
    return bool(getattr(result, "rowcount", 0))


async def handle_post_video_fixed_user_reply(
    db: AsyncSession,
    *,
    conversation_id: str,
    text_value: str | None,
    is_screenshot: bool,
    trace_id: str | None = None,
    message_id: str | None = None,
    chat_fn: ChatFn | None = None,
) -> bool:
    """Return True when the system must stop all further automated actions."""
    await ensure_post_video_fixed_columns(db)
    if await is_post_video_fixed_03_stopped(db, conversation_id=conversation_id):
        return True
    reason = None
    if is_screenshot:
        reason = "screenshot"
    else:
        state = await _conversation_state(db, conversation_id=conversation_id, external_user_id=None)
        if _in_post_video_funnel(state) and await classify_already_registered_reply(
            text_value, trace_id=trace_id, chat_fn=chat_fn
        ):
            reason = "already_registered"
    if not reason:
        return False
    if reason == "already_registered" and message_id:
        await db.execute(
            text(
                """
                UPDATE messages
                   SET model_name = :model_name
                 WHERE id = CAST(:mid AS uuid)
                   AND (model_name IS NULL OR btrim(model_name) = '')
                """
            ),
            {"mid": message_id, "model_name": REGISTERED_INTENT_MODEL_NAME},
        )
    newly = await mark_post_video_fixed_03_stopped(
        db,
        conversation_id=conversation_id,
        reason=reason,
    )
    logger.bind(
        component="post_inbound_video_fixed",
        trace_id=trace_id,
        conversation_id=conversation_id,
        reason=reason,
        newly_stopped=newly,
    ).info("post_inbound_video_fixed.03_stopped")
    return True


async def _load_rule_by_name(db: AsyncSession, name: str) -> dict[str, Any] | None:
    row = (
        await db.execute(
            text(
                """
                SELECT id::text, title AS name, content AS text_content
                  FROM script_templates
                 WHERE title = :name
                   AND status = 'approved'
                 ORDER BY CASE WHEN language = 'en' THEN 0 ELSE 1 END,
                          updated_at DESC NULLS LAST
                 LIMIT 1
                """
            ),
            {"name": name},
        )
    ).mappings().first()
    if not row:
        return None
    assets = (
        await db.execute(
            text(
                """
                SELECT id, asset_type, asset_url, storage_path, caption, sort_order
                  FROM script_template_assets
                 WHERE script_template_id = CAST(:script_id AS uuid)
                   AND is_active = TRUE
                 ORDER BY sort_order ASC, created_at ASC
                """
            ),
            {"script_id": row["id"]},
        )
    ).mappings().all()
    data = dict(row)
    data["assets"] = [dict(item) for item in assets]
    return data


async def _prepare_script_outbound(
    db: AsyncSession,
    *,
    text_content: str,
    account_id: str,
    conversation_id: str | None,
    rule_name: str,
    script_id: str,
    trace_id: str | None,
) -> tuple[str, str, dict[str, Any]]:
    outbound_text = text_content
    send_kwargs: dict[str, Any] = {}
    if "http" in text_content:
        try:
            user_id = None
            if conversation_id:
                user_id = (
                    await db.execute(
                        text(
                            "SELECT user_id::text FROM conversations WHERE id = CAST(:id AS uuid)"
                        ),
                        {"id": conversation_id},
                    )
                ).scalar()
            outbound_text = await wrap_text_links_with_tracking(
                db,
                text_value=text_content,
                base_url=str(settings.PUBLIC_BASE_URL).rstrip("/"),
                user_id=user_id,
                conversation_id=conversation_id,
                script_hit_id=script_id or None,
                platform="telegram_real_user",
                sender_account_id=str(account_id),
                script_category="post_inbound_video_script",
                intent="post_inbound_video_script",
                metadata={
                    "source": "post_inbound_video_script",
                    "title": rule_name,
                    "trace_id": trace_id,
                },
            )
        except Exception as exc:
            logger.bind(
                error_type=type(exc).__name__,
                rule_name=rule_name,
                trace_id=trace_id,
            ).warning("post_inbound_video_fixed.link_attribution_failed")
            outbound_text = text_content
    telegram_text = render_tracking_links_as_html_cta(outbound_text)
    if telegram_text != outbound_text:
        send_kwargs["parse_mode"] = "html"
    return outbound_text, telegram_text, send_kwargs


async def _persist_assistant_text(
    db: AsyncSession,
    *,
    conversation_id: str | None,
    account_id: str,
    content: str,
    model_name: str,
) -> None:
    if not conversation_id or not content.strip():
        return
    await db.execute(
        text(
            """
            INSERT INTO messages (
                id, conversation_id, sender_type, sender_id, content,
                content_type, model_name, created_at
            )
            VALUES (
                :id, CAST(:conversation_id AS uuid), 'assistant', :sender_id,
                :content, 'text', :model_name, NOW()
            )
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "conversation_id": conversation_id,
            "sender_id": str(account_id),
            "content": content,
            "model_name": model_name,
        },
    )
    await db.execute(
        text(
            "UPDATE conversations SET last_message_at=NOW(), updated_at=NOW() WHERE id=CAST(:id AS uuid)"
        ),
        {"id": conversation_id},
    )


async def send_named_fixed_rule(
    db: AsyncSession,
    *,
    rule_name: str,
    account_id: str,
    chat_id: int,
    telegram_access_hash: int | None,
    conversation_id: str | None,
    trace_id: str | None,
) -> bool:
    log = logger.bind(
        component="post_inbound_video_fixed",
        trace_id=trace_id,
        rule_name=rule_name,
        account_id=account_id,
        chat_id=chat_id,
    )
    rule = await _load_rule_by_name(db, rule_name)
    if rule is None:
        log.warning("post_inbound_video_fixed.rule_missing")
        return False
    text_content = str(rule.get("text_content") or "").strip()
    assets = list(rule.get("assets") or [])
    if not text_content and not assets:
        log.warning("post_inbound_video_fixed.rule_empty")
        return False

    allowed, gate_reason, _resume_at = await check_outbound_account(db, account_id)
    if not allowed:
        log.bind(gate_reason=gate_reason).warning("post_inbound_video_fixed.account_gated")
        return False

    client = await telegram_account_manager.get_client(uuid.UUID(str(account_id)))
    if client is None:
        log.warning("post_inbound_video_fixed.no_client")
        return False
    peer = await resolve_telethon_peer(client, int(chat_id), access_hash=telegram_access_hash)
    if text_content:
        outbound_text, telegram_text, send_kwargs = await _prepare_script_outbound(
            db,
            text_content=text_content,
            account_id=account_id,
            conversation_id=conversation_id,
            rule_name=rule_name,
            script_id=str(rule.get("id") or ""),
            trace_id=trace_id,
        )
        await client.send_message(peer, telegram_text, **send_kwargs)
        await _persist_assistant_text(
            db,
            conversation_id=conversation_id,
            account_id=account_id,
            content=outbound_text,
            model_name=f"post_video_script:{rule_name}",
        )
    for asset in assets:
        sent = await send_mtproto_asset(client, peer, asset, trace_id=trace_id)
        if sent is None:
            log.bind(asset_id=str(asset.get("id") or "")).warning(
                "post_inbound_video_fixed.asset_send_failed"
            )
            return False
    log.info("post_inbound_video_fixed.sent")
    return True


async def maybe_send_after_two_auto_answers(
    db: AsyncSession,
    *,
    account_id: str,
    chat_id: int,
    telegram_access_hash: int | None,
    completed_auto_answer_count: int,
    trace_id: str | None,
    conversation_id: str | None = None,
    external_user_id: str | None = None,
    delay_seconds: int | None = None,
) -> dict[str, bool]:
    """After two successful auto-answers: send 01, wait 5s, send 02. Once only."""
    result = {"sent_01": False, "sent_02": False}
    if int(completed_auto_answer_count or 0) < 2:
        return result
    await ensure_post_video_fixed_columns(db)
    ext = external_user_id or f"tg_{int(chat_id)}"
    state = await _ensure_conversation_for_chat(
        db,
        chat_id=chat_id,
        conversation_id=conversation_id,
        external_user_id=ext,
    )
    if not state:
        logger.bind(chat_id=chat_id, trace_id=trace_id).warning(
            "post_inbound_video_fixed.no_conversation"
        )
        return result
    cid = str(state["id"])
    if state.get("post_video_fixed_03_stopped_at"):
        return result
    if should_skip_post_video_auto_send(
        conversation_state=state.get("state"),
        operator_replied=state.get("operator_replied"),
    ):
        logger.bind(
            conversation_id=cid,
            conversation_state=str(state.get("state") or ""),
            operator_replied=bool(state.get("operator_replied")),
            chat_id=chat_id,
            trace_id=trace_id,
        ).info("post_inbound_video_fixed.skip_human_control")
        return result

    if not state.get("post_video_fixed_01_sent_at"):
        ok = await send_named_fixed_rule(
            db,
            rule_name=RULE_01,
            account_id=account_id,
            chat_id=chat_id,
            telegram_access_hash=telegram_access_hash,
            conversation_id=cid,
            trace_id=trace_id,
        )
        if ok:
            await db.execute(
                text(
                    """
                    UPDATE conversations
                       SET post_video_fixed_01_sent_at = NOW(), updated_at = NOW()
                     WHERE id = CAST(:cid AS uuid)
                    """
                ),
                {"cid": cid},
            )
            await db.commit()
            result["sent_01"] = True

    wait_s = POST_VIDEO_FIXED_02_DELAY_SECONDS if delay_seconds is None else max(0, int(delay_seconds))
    if wait_s:
        await asyncio.sleep(wait_s)

    state = await _conversation_state(db, conversation_id=cid, external_user_id=ext)
    if not state or state.get("post_video_fixed_03_stopped_at"):
        return result
    if should_skip_post_video_auto_send(
        conversation_state=state.get("state"),
        operator_replied=state.get("operator_replied"),
    ):
        logger.bind(
            conversation_id=cid,
            conversation_state=str(state.get("state") or ""),
            operator_replied=bool(state.get("operator_replied")),
            chat_id=chat_id,
            trace_id=trace_id,
        ).info("post_inbound_video_fixed.skip_human_control")
        return result
    if not state.get("post_video_fixed_02_sent_at"):
        ok = await send_named_fixed_rule(
            db,
            rule_name=RULE_02,
            account_id=account_id,
            chat_id=chat_id,
            telegram_access_hash=telegram_access_hash,
            conversation_id=cid,
            trace_id=trace_id,
        )
        if ok:
            await db.execute(
                text(
                    """
                    UPDATE conversations
                       SET post_video_fixed_02_sent_at = NOW(), updated_at = NOW()
                     WHERE id = CAST(:cid AS uuid)
                    """
                ),
                {"cid": cid},
            )
            await db.commit()
            result["sent_02"] = True
    return result


async def maybe_send_03_on_later_inbound_call(
    db: AsyncSession,
    *,
    account_id: str,
    chat_id: int,
    telegram_access_hash: int | None,
    completed_playbacks: int,
    trace_id: str | None,
    conversation_id: str | None = None,
    external_user_id: str | None = None,
) -> bool:
    """From the 3rd valid inbound call onward, send 03 once per call until stopped."""
    if int(completed_playbacks or 0) < 2:
        return False
    await ensure_post_video_fixed_columns(db)
    ext = external_user_id or f"tg_{int(chat_id)}"
    state = await _ensure_conversation_for_chat(
        db,
        chat_id=chat_id,
        conversation_id=conversation_id,
        external_user_id=ext,
    )
    if not state or state.get("post_video_fixed_03_stopped_at"):
        return False
    cid = str(state["id"])
    if should_skip_post_video_auto_send(
        conversation_state=state.get("state"),
        operator_replied=state.get("operator_replied"),
    ):
        logger.bind(
            conversation_id=cid,
            conversation_state=str(state.get("state") or ""),
            operator_replied=bool(state.get("operator_replied")),
            chat_id=chat_id,
            trace_id=trace_id,
        ).info("post_inbound_video_fixed.skip_human_control")
        return False
    claimed = (
        await db.execute(
            text(
                """
                UPDATE conversations
                   SET post_video_fixed_03_last_sent_at = NOW(), updated_at = NOW()
                 WHERE id = CAST(:cid AS uuid)
                   AND post_video_fixed_03_stopped_at IS NULL
                   AND (
                     post_video_fixed_03_last_sent_at IS NULL
                     OR post_video_fixed_03_last_sent_at
                        < NOW() - (:debounce_seconds * INTERVAL '1 second')
                   )
             RETURNING id::text
                """
            ),
            {"cid": cid, "debounce_seconds": POST_VIDEO_FIXED_03_DEBOUNCE_SECONDS},
        )
    ).first()
    if claimed is None:
        await db.rollback()
        logger.bind(
            conversation_id=cid,
            chat_id=chat_id,
            trace_id=trace_id,
        ).info("post_inbound_video_fixed.skip_03_debounce")
        return False
    await db.commit()
    ok = await send_named_fixed_rule(
        db,
        rule_name=RULE_03,
        account_id=account_id,
        chat_id=chat_id,
        telegram_access_hash=telegram_access_hash,
        conversation_id=cid,
        trace_id=trace_id,
    )
    return ok
