"""Read Telegram's phone-country (the flag shown for non-contacts)."""

from __future__ import annotations

import asyncio
import unicodedata
from dataclasses import dataclass
from typing import Any

from loguru import logger

from services.profile_intake import normalize_country_code

PEER_SETTINGS_TIMEOUT_SECONDS = 4.0
PHONE_COUNTRY_DISPLAY_ALIASES = {
    "USA": "US",
    "UNITED STATES": "US",
    "PERU": "PE",
    "MEXICO": "MX",
    "GUATEMALA": "GT",
}


@dataclass(frozen=True)
class PeerPhoneCountry:
    country_code: str | None
    registration_month: str | None
    raw_phone_country: str | None


def _fold_display_name(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in folded if not unicodedata.combining(ch)).upper().strip()


def country_from_phone_country_field(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    code = normalize_country_code(raw)
    if code:
        return code
    return PHONE_COUNTRY_DISPLAY_ALIASES.get(_fold_display_name(raw))


def parse_peer_settings(payload: Any) -> PeerPhoneCountry:
    """Extract ISO country + registration month from PeerSettings / GetPeerSettings result."""
    settings = getattr(payload, "settings", None)
    if settings is None:
        settings = payload
    if isinstance(payload, dict) and "settings" in payload:
        settings = payload.get("settings")
    raw = None
    month = None
    if isinstance(settings, dict):
        raw = settings.get("phone_country")
        month = settings.get("registration_month")
    else:
        raw = getattr(settings, "phone_country", None)
        month = getattr(settings, "registration_month", None)
    raw_text = str(raw).strip() if raw is not None else ""
    month_text = str(month).strip() if month is not None else ""
    return PeerPhoneCountry(
        country_code=country_from_phone_country_field(raw_text) if raw_text else None,
        registration_month=month_text or None,
        raw_phone_country=raw_text or None,
    )


def should_refresh_phone_country(
    *,
    existing_country_code: str | None,
    country_source: str | None,
    already_fetched: bool,
) -> bool:
    if already_fetched:
        return False
    return str(country_source or "").strip() != "telegram_phone_country"


async def fetch_peer_phone_country(client: Any, peer: Any) -> PeerPhoneCountry:
    """Call messages.getPeerSettings — same source as the Telegram client info card."""
    from telethon.tl.functions.messages import GetPeerSettingsRequest

    result = await asyncio.wait_for(
        client(GetPeerSettingsRequest(peer=peer)),
        timeout=PEER_SETTINGS_TIMEOUT_SECONDS,
    )
    parsed = parse_peer_settings(result)
    logger.bind(
        phone_country=parsed.raw_phone_country,
        country_code=parsed.country_code,
        registration_month=parsed.registration_month,
    ).info("mtproto.peer_settings.phone_country")
    return parsed
