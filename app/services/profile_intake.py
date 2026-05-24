"""Country and age intake helpers for early user grading."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

COUNTRY_ALIASES: dict[str, str] = {
    "US": "US",
    "USA": "US",
    "UNITED STATES": "US",
    "AMERICA": "US",
    "美国": "US",
    "CA": "CA",
    "CANADA": "CA",
    "加拿大": "CA",
    "GB": "GB",
    "UK": "GB",
    "UNITED KINGDOM": "GB",
    "BRITAIN": "GB",
    "ENGLAND": "GB",
    "英国": "GB",
    "DE": "DE",
    "GERMANY": "DE",
    "德国": "DE",
    "FR": "FR",
    "FRANCE": "FR",
    "法国": "FR",
    "IT": "IT",
    "ITALY": "IT",
    "意大利": "IT",
    "ES": "ES",
    "SPAIN": "ES",
    "西班牙": "ES",
    "NL": "NL",
    "NETHERLANDS": "NL",
    "HOLLAND": "NL",
    "荷兰": "NL",
    "BE": "BE",
    "BELGIUM": "BE",
    "比利时": "BE",
    "CH": "CH",
    "SWITZERLAND": "CH",
    "瑞士": "CH",
    "AT": "AT",
    "AUSTRIA": "AT",
    "奥地利": "AT",
    "IE": "IE",
    "IRELAND": "IE",
    "爱尔兰": "IE",
    "DK": "DK",
    "DENMARK": "DK",
    "丹麦": "DK",
    "NO": "NO",
    "NORWAY": "NO",
    "挪威": "NO",
    "SE": "SE",
    "SWEDEN": "SE",
    "瑞典": "SE",
    "FI": "FI",
    "FINLAND": "FI",
    "芬兰": "FI",
    "IS": "IS",
    "ICELAND": "IS",
    "冰岛": "IS",
    "LU": "LU",
    "LUXEMBOURG": "LU",
    "卢森堡": "LU",
    "PT": "PT",
    "PORTUGAL": "PT",
    "葡萄牙": "PT",
    "GR": "GR",
    "GREECE": "GR",
    "希腊": "GR",
    "CZ": "CZ",
    "CZECH": "CZ",
    "CZECH REPUBLIC": "CZ",
    "CZECHIA": "CZ",
    "捷克": "CZ",
    "JP": "JP",
    "JAPAN": "JP",
    "日本": "JP",
    "AU": "AU",
    "AUSTRALIA": "AU",
    "澳大利亚": "AU",
    "NZ": "NZ",
    "NEW ZEALAND": "NZ",
    "新西兰": "NZ",
    "SG": "SG",
    "SINGAPORE": "SG",
    "新加坡": "SG",
    "HK": "HK",
    "HONG KONG": "HK",
    "香港": "HK",
    "中国香港": "HK",
}

COUNTRY_HEADER_NAMES = (
    "cf-ipcountry",
    "x-vercel-ip-country",
    "cloudfront-viewer-country",
    "x-country-code",
    "x-geo-country",
)

LANGUAGE_COUNTRY_HINTS = {
    "de": "DE",
    "fr": "FR",
    "it": "IT",
    "ja": "JP",
    "nl": "NL",
    "sv": "SE",
    "da": "DK",
    "fi": "FI",
    "nb": "NO",
    "nn": "NO",
    "no": "NO",
    "is": "IS",
}

AGE_MIN = 13
AGE_MAX = 120


@dataclass(frozen=True)
class ProfileCompleteness:
    country_code: str | None
    age: int | None

    @property
    def complete(self) -> bool:
        return self.country_code is not None and self.age is not None

    @property
    def missing_fields(self) -> tuple[str, ...]:
        fields: list[str] = []
        if self.country_code is None:
            fields.append("country_code")
        if self.age is None:
            fields.append("age")
        return tuple(fields)


def normalize_country_code(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    upper = re.sub(r"\s+", " ", raw).upper()
    if upper in {"XX", "UNKNOWN", "ZZ"}:
        return None
    if upper in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[upper]
    if re.fullmatch(r"[A-Z]{2}", upper):
        return upper
    for alias, code in COUNTRY_ALIASES.items():
        if len(alias) > 2 and alias in upper:
            return code
    return None


def country_from_metadata(metadata: Mapping[str, Any] | None) -> str | None:
    if not metadata:
        return None
    for key in ("country_code", "country", "geo_country", "ip_country"):
        code = normalize_country_code(metadata.get(key))
        if code:
            return code
    return None


def country_from_headers(headers: Mapping[str, Any] | None) -> str | None:
    if not headers:
        return None
    for name in COUNTRY_HEADER_NAMES:
        code = normalize_country_code(headers.get(name))
        if code:
            return code
    return None


def country_from_locale(locale: Any) -> str | None:
    if locale is None:
        return None
    value = str(locale).strip().replace("_", "-")
    if not value:
        return None
    parts = [part for part in value.split("-") if part]
    if len(parts) >= 2:
        code = normalize_country_code(parts[-1])
        if code:
            return code
    return LANGUAGE_COUNTRY_HINTS.get(parts[0].lower()) if parts else None


def parse_age_value(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        age = int(value)
    except (TypeError, ValueError):
        return None
    return age if AGE_MIN <= age <= AGE_MAX else None


def extract_age_from_text(text_value: str) -> int | None:
    value = (text_value or "").strip()
    if not value:
        return None
    direct = parse_age_value(value)
    if direct is not None:
        return direct
    patterns = (
        r"\b(?:i am|i'm|im|age is|aged)\s*(\d{1,3})\b",
        r"\b(\d{1,3})\s*(?:years old|yrs old|yo|y/o)\b",
        r"(?:我|本人)?\s*(\d{1,3})\s*岁",
    )
    for pattern in patterns:
        match = re.search(pattern, value, re.I)
        if match:
            age = parse_age_value(match.group(1))
            if age is not None:
                return age
    return None


def age_from_preferences(preferences: Mapping[str, Any] | None) -> int | None:
    if not isinstance(preferences, Mapping):
        return None
    for key in ("age", "user_age"):
        age = parse_age_value(preferences.get(key))
        if age is not None:
            return age
    extracted = preferences.get("ai_extracted_age")
    if isinstance(extracted, Mapping):
        return parse_age_value(extracted.get("age"))
    return None


def profile_completeness(
    *,
    country_code: Any = None,
    preferences: Mapping[str, Any] | None = None,
) -> ProfileCompleteness:
    return ProfileCompleteness(
        country_code=normalize_country_code(country_code)
        or country_from_metadata(preferences),
        age=age_from_preferences(preferences),
    )


async def read_profile_completeness(
    db: AsyncSession,
    *,
    user_id: str,
) -> ProfileCompleteness:
    row = (
        await db.execute(
            text(
                """
                SELECT country_code, preferences
                FROM user_profiles
                WHERE user_id = CAST(:uid AS uuid)
                """
            ),
            {"uid": user_id},
        )
    ).fetchone()
    if not row:
        return ProfileCompleteness(country_code=None, age=None)
    data = row._mapping if hasattr(row, "_mapping") else row
    preferences = _as_dict(data["preferences"])
    return profile_completeness(
        country_code=data["country_code"] if hasattr(data, "__getitem__") else None,
        preferences=preferences,
    )


async def write_country_code(
    db: AsyncSession,
    *,
    user_id: str,
    country_code: str,
    source: str,
) -> None:
    code = normalize_country_code(country_code)
    if not code:
        return
    await db.execute(
        text(
            """
            UPDATE user_profiles
            SET country_code = :country_code,
                preferences = jsonb_set(
                    jsonb_set(
                        COALESCE(preferences, '{}'::jsonb),
                        '{country_code}',
                        to_jsonb(CAST(:country_code AS text)),
                        true
                    ),
                    '{country_source}',
                    to_jsonb(CAST(:source AS text)),
                    true
                ),
                updated_at = NOW()
            WHERE user_id = CAST(:uid AS uuid)
            """
        ),
        {"uid": user_id, "country_code": code, "source": source},
    )


async def write_age(
    db: AsyncSession,
    *,
    user_id: str,
    age: int,
    source: str,
) -> None:
    parsed = parse_age_value(age)
    if parsed is None:
        return
    await db.execute(
        text(
            """
            UPDATE user_profiles
            SET preferences = jsonb_set(
                    jsonb_set(
                        COALESCE(preferences, '{}'::jsonb),
                        '{age}',
                        to_jsonb(CAST(:age AS int)),
                        true
                    ),
                    '{age_source}',
                    to_jsonb(CAST(:source AS text)),
                    true
                ),
                updated_at = NOW()
            WHERE user_id = CAST(:uid AS uuid)
            """
        ),
        {"uid": user_id, "age": parsed, "source": source},
    )


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
    return {}
