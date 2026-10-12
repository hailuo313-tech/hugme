from __future__ import annotations

import html
import json
import re
import secrets
import string
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DEVICE_OS_ANDROID = "Android"
DEVICE_OS_IOS = "iOS"
DEVICE_OS_DESKTOP = "Desktop"
DEVICE_OS_UNKNOWN = "Unknown"


def normalize_device_os(value: str | None) -> str:
    raw = str(value or "").strip().casefold()
    if raw == "android":
        return DEVICE_OS_ANDROID
    if raw in {"ios", "iphone", "ipad", "ipod"}:
        return DEVICE_OS_IOS
    if raw in {"desktop", "windows", "macos", "linux", "chromeos"}:
        return DEVICE_OS_DESKTOP
    return DEVICE_OS_UNKNOWN


def detect_device_os(user_agent: str | None) -> str:
    ua = str(user_agent or "").casefold()
    if "android" in ua:
        return DEVICE_OS_ANDROID
    if any(token in ua for token in ("iphone", "ipad", "ipod")):
        return DEVICE_OS_IOS
    if any(token in ua for token in ("windows nt", "macintosh", "x11", "cros")):
        return DEVICE_OS_DESKTOP
    return DEVICE_OS_UNKNOWN


async def _save_user_device(
    db: AsyncSession,
    *,
    user_id: Any,
    device_os: str,
    user_agent: str | None,
) -> None:
    if not user_id or device_os == DEVICE_OS_UNKNOWN:
        return
    await db.execute(
        text(
            """
            INSERT INTO user_profiles (
                user_id, device_os, device_user_agent,
                device_first_detected_at, device_last_detected_at, updated_at
            ) VALUES (
                CAST(:user_id AS uuid), :device_os, :user_agent,
                NOW(), NOW(), NOW()
            )
            ON CONFLICT (user_id) DO UPDATE
            SET device_os = EXCLUDED.device_os,
                device_user_agent = EXCLUDED.device_user_agent,
                device_first_detected_at = COALESCE(
                    user_profiles.device_first_detected_at,
                    EXCLUDED.device_first_detected_at
                ),
                device_last_detected_at = EXCLUDED.device_last_detected_at,
                updated_at = NOW()
            """
        ),
        {"user_id": user_id, "device_os": device_os, "user_agent": user_agent},
    )


TRACKING_ID_LENGTH = 18
TRACKING_ID_ALPHABET = string.ascii_letters + string.digits
ALLOWED_EVENT_TYPES = {
    "link_exposed",
    "click",
    "download_page",
    "download",
    "app_register",
    "payment",
}
URL_RE = re.compile(r"https?://[^\s<>\]\"']+")
TRACKING_URL_RE = re.compile(r"https?://[^\s<>\]\"']+/r/[A-Za-z0-9]+")
TRAILING_URL_PUNCTUATION = ".,!?;:)"


def new_tracking_id() -> str:
    return "".join(secrets.choice(TRACKING_ID_ALPHABET) for _ in range(TRACKING_ID_LENGTH))


async def create_attribution_link(
    db: AsyncSession,
    *,
    destination_url: str,
    tracking_id: str | None = None,
    user_id: Any = None,
    conversation_id: Any = None,
    message_id: Any = None,
    script_hit_id: str | None = None,
    script_template_id: Any = None,
    campaign_id: str | None = None,
    platform: str | None = None,
    persona_slug: str | None = None,
    intent: str | None = None,
    sender_account_id: str | None = None,
    scene_step: str | None = None,
    script_category: str | None = None,
    is_t1_country: bool | None = None,
    country_code: str | None = None,
    age: int | None = None,
    user_level: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    if platform in (None, "", "telegram_real_user"):
        from services.app_download_platforms import resolve_app_download_route_context

        route = await resolve_app_download_route_context(
            db,
            destination_url=destination_url,
            account_id=sender_account_id,
            conversation_id=str(conversation_id) if conversation_id else None,
            user_id=str(user_id) if user_id else None,
        )
        platform = str(route.get("platform_key") or "default")
        country_code = country_code or route.get("country_code")
        if is_t1_country is None:
            is_t1_country = bool(route.get("is_t1_country"))
    tracking_id = tracking_id or new_tracking_id()
    await db.execute(
        text(
            """
            INSERT INTO attribution_links (
                tracking_id, destination_url, user_id, conversation_id, message_id,
                script_hit_id, script_template_id, campaign_id, platform,
                persona_slug, intent, sender_account_id, scene_step, script_category,
                is_t1_country, country_code, age, user_level, metadata
            )
            VALUES (
                :tracking_id, :destination_url, :user_id,
                (SELECT id FROM conversations WHERE id = CAST(:conversation_id AS uuid)),
                (SELECT id FROM messages WHERE id = CAST(:message_id AS uuid)),
                :script_hit_id, :script_template_id, :campaign_id, :platform,
                :persona_slug, :intent, :sender_account_id, :scene_step, :script_category,
                :is_t1_country, :country_code, :age, :user_level,
                CAST(:metadata AS JSONB)
            )
            """
        ),
        {
            "tracking_id": tracking_id,
            "destination_url": destination_url,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "script_hit_id": script_hit_id,
            "script_template_id": script_template_id,
            "campaign_id": campaign_id,
            "platform": platform,
            "persona_slug": persona_slug,
            "intent": intent,
            "sender_account_id": sender_account_id,
            "scene_step": scene_step,
            "script_category": script_category,
            "is_t1_country": is_t1_country,
            "country_code": country_code.upper() if country_code else None,
            "age": age,
            "user_level": user_level.upper() if user_level else None,
            "metadata": json.dumps(metadata or {}, ensure_ascii=False),
        },
    )
    return tracking_id


async def wrap_text_links_with_tracking(
    db: AsyncSession,
    *,
    text_value: str,
    base_url: str,
    user_id: Any = None,
    conversation_id: Any = None,
    message_id: Any = None,
    script_hit_id: str | None = None,
    campaign_id: str | None = None,
    platform: str | None = None,
    sender_account_id: str | None = None,
    scene_step: str | None = None,
    script_category: str | None = None,
    persona_slug: str | None = None,
    intent: str | None = None,
    country_code: str | None = None,
    age: int | None = None,
    user_level: str | None = None,
    is_t1_country: bool | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Replace http(s) links in outgoing text with /r/{tracking_id} links."""
    if not text_value or "http" not in text_value:
        return text_value

    output: list[str] = []
    last = 0
    for match in URL_RE.finditer(text_value):
        raw_url = match.group(0)
        destination_url = raw_url.rstrip(TRAILING_URL_PUNCTUATION)
        suffix = raw_url[len(destination_url):]
        output.append(text_value[last:match.start()])
        if f"{base_url.rstrip('/')}/r/" in destination_url:
            output.append(raw_url)
        else:
            tracking_id = await create_attribution_link(
                db,
                destination_url=destination_url,
                user_id=user_id,
                conversation_id=conversation_id,
                message_id=message_id,
                script_hit_id=script_hit_id,
                campaign_id=campaign_id,
                platform=platform,
                sender_account_id=sender_account_id,
                scene_step=scene_step,
                script_category=script_category,
                persona_slug=persona_slug,
                intent=intent,
                country_code=country_code,
                age=age,
                user_level=user_level,
                is_t1_country=is_t1_country,
                metadata=metadata,
            )
            await record_attribution_event(
                db,
                tracking_id=tracking_id,
                event_type="link_exposed",
                user_id=user_id,
                country_code=country_code,
                age=age,
                user_level=user_level,
                metadata_json=json.dumps(
                    {
                        "source": "outbound_link_wrap",
                        "message_id": str(message_id) if message_id else None,
                        "script_hit_id": script_hit_id,
                        "campaign_id": campaign_id,
                        **(metadata or {}),
                    },
                    ensure_ascii=False,
                ),
            )
            output.append(tracking_url(base_url, tracking_id))
            output.append(suffix)
        last = match.end()
    output.append(text_value[last:])
    return "".join(output)


async def record_attribution_event(
    db: AsyncSession,
    *,
    tracking_id: str | None,
    event_type: str,
    user_id: Any = None,
    app_user_id: str | None = None,
    order_id: Any = None,
    amount_cents: int | None = None,
    currency: str | None = None,
    country_code: str | None = None,
    age: int | None = None,
    user_level: str | None = None,
    device_os: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    referrer: str | None = None,
    metadata_json: str = "{}",
) -> None:
    if event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError(f"unsupported attribution event_type: {event_type}")

    resolved_device_os = normalize_device_os(device_os) if device_os else detect_device_os(user_agent)
    await db.execute(
        text(
            """
            INSERT INTO attribution_events (
                tracking_id, event_type, user_id, app_user_id, order_id,
                amount_cents, currency, country_code, age, user_level,
                device_os, ip_address, user_agent, referrer, metadata
            )
            VALUES (
                :tracking_id, :event_type, :user_id, :app_user_id, :order_id,
                :amount_cents, :currency, :country_code, :age, :user_level,
                :device_os, CAST(:ip_address AS INET), :user_agent, :referrer,
                CAST(:metadata AS JSONB)
            )
            """
        ),
        {
            "tracking_id": tracking_id,
            "event_type": event_type,
            "user_id": user_id,
            "app_user_id": app_user_id,
            "order_id": order_id,
            "amount_cents": amount_cents,
            "currency": currency,
            "country_code": country_code.upper() if country_code else None,
            "age": age,
            "user_level": user_level.upper() if user_level else None,
            "device_os": resolved_device_os,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "referrer": referrer,
            "metadata": metadata_json,
        },
    )
    await _save_user_device(db, user_id=user_id, device_os=resolved_device_os, user_agent=user_agent)


async def record_unique_click_event(
    db: AsyncSession,
    *,
    tracking_id: str | None,
    user_id: Any = None,
    country_code: str | None = None,
    age: int | None = None,
    user_level: str | None = None,
    device_os: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    referrer: str | None = None,
    metadata_json: str = "{}",
) -> None:
    """Record only the first click for a tracked user/link pair."""
    resolved_device_os = normalize_device_os(device_os) if device_os else detect_device_os(user_agent)
    await db.execute(
        text(
            """
            INSERT INTO attribution_events (
                tracking_id, event_type, user_id, country_code, age, user_level,
                device_os, ip_address, user_agent, referrer, metadata
            )
            SELECT
                CAST(:tracking_id AS varchar), 'click', CAST(:user_id AS uuid), :country_code, :age, :user_level,
                :device_os, CAST(:ip_address AS INET), :user_agent, :referrer,
                CAST(:metadata AS JSONB)
            WHERE NOT EXISTS (
                SELECT 1
                FROM attribution_events
                WHERE tracking_id IS NOT DISTINCT FROM CAST(:tracking_id AS varchar)
                  AND event_type = 'click'
                  AND (
                    (CAST(:user_id AS uuid) IS NOT NULL AND user_id = CAST(:user_id AS uuid))
                    OR (
                        CAST(:user_id AS uuid) IS NULL
                        AND user_id IS NULL
                        AND ip_address IS NOT DISTINCT FROM CAST(:ip_address AS INET)
                        AND COALESCE(user_agent, '') = COALESCE(:user_agent, '')
                    )
                  )
            )
            """
        ),
        {
            "tracking_id": tracking_id,
            "user_id": user_id,
            "country_code": country_code.upper() if country_code else None,
            "age": age,
            "user_level": user_level.upper() if user_level else None,
            "device_os": resolved_device_os,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "referrer": referrer,
            "metadata": metadata_json,
        },
    )
    await _save_user_device(db, user_id=user_id, device_os=resolved_device_os, user_agent=user_agent)


def tracking_url(base_url: str, tracking_id: str) -> str:
    return f"{base_url.rstrip('/')}/r/{tracking_id}"


def render_tracking_links_as_html_cta(
    text_value: str,
    *,
    cta_label: str | None = None,
    language: str | None = None,
    user_text: str | None = None,
) -> str:
    """Render each tracked URL as exactly one Telegram click target.

    Keep the CTA label as plain text and make only the canonical ``/r/{id}``
    URL clickable.  Binding both the label and the visible URL to the same href
    makes Telegram present two links for one attribution record and confuses
    users even though both destinations are identical.
    """
    if not text_value or "/r/" not in text_value:
        return text_value

    if not cta_label:
        from services.product_i18n import tracking_cta_label

        cta_label = tracking_cta_label(language, user_text=user_text)

    output: list[str] = []
    last = 0
    changed = False
    for match in TRACKING_URL_RE.finditer(text_value):
        raw_url = match.group(0)
        tracked_url = raw_url.rstrip(TRAILING_URL_PUNCTUATION)
        suffix = raw_url[len(tracked_url):]
        output.append(html.escape(text_value[last:match.start()]))
        escaped_url_attr = html.escape(tracked_url, quote=True)
        escaped_url_text = html.escape(tracked_url)
        escaped_label = html.escape(cta_label)
        output.append(
            f'{escaped_label}\n'
            f'🔗 <a href="{escaped_url_attr}">{escaped_url_text}</a>'
        )
        output.append(html.escape(suffix))
        last = match.end()
        changed = True
    output.append(html.escape(text_value[last:]))
    return "".join(output) if changed else text_value
