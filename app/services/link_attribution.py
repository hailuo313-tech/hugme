from __future__ import annotations

import json
import re
import secrets
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


TRACKING_ID_BYTES = 12
ALLOWED_EVENT_TYPES = {
    "link_exposed",
    "click",
    "download_page",
    "download",
    "app_register",
    "payment",
}
URL_RE = re.compile(r"https?://[^\s<>\]\"']+")
TRAILING_URL_PUNCTUATION = ".,!?;:)"


def new_tracking_id() -> str:
    return secrets.token_urlsafe(TRACKING_ID_BYTES)


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
                :tracking_id, :destination_url, :user_id, :conversation_id,
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
            "device_os": device_os,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "referrer": referrer,
            "metadata": metadata_json,
        },
    )


def tracking_url(base_url: str, tracking_id: str) -> str:
    return f"{base_url.rstrip('/')}/r/{tracking_id}"
