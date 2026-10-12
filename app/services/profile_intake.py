"""Country and age intake helpers for early user grading."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from services.emotion_lexicon import detect_language_from_text, normalize_language

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
    "MX": "MX",
    "MEX": "MX",
    "MEXICO": "MX",
    "MEXICO CITY": "MX",
    "CDMX": "MX",
    "墨西哥": "MX",
    "MY": "MY",
    "MALAYSIA": "MY",
    "MALAYSIA..": "MY",
    "马来西亚": "MY",
    "VE": "VE",
    "VENEZUELA": "VE",
    "委内瑞拉": "VE",
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
    "NG": "NG",
    "NIGERIA": "NG",
    "MONTENEGRO": "ME",
    "香港": "HK",
    "中国香港": "HK",
}

# Common short chat replies that also happen to be ISO country codes.
# Accept their full country names instead of treating bare words as country answers.
AMBIGUOUS_BARE_COUNTRY_TOKENS = {
    "AM",
    "BB",
    "EU",
    "HI",
    "HL",
    "HO",
    "HY",
    "IM",
    "IN",
    "JA",
    "ME",
    "MY",
    "NO",
    "OH",
    "OI",
    "OK",
    "OL",
    "SI",
    "YA",
    "YO",
}

ISO_ALPHA2_COUNTRY_CODES = {
    "AD",
    "AE",
    "AF",
    "AG",
    "AI",
    "AL",
    "AM",
    "AO",
    "AQ",
    "AR",
    "AS",
    "AT",
    "AU",
    "AW",
    "AX",
    "AZ",
    "BA",
    "BB",
    "BD",
    "BE",
    "BF",
    "BG",
    "BH",
    "BI",
    "BJ",
    "BL",
    "BM",
    "BN",
    "BO",
    "BQ",
    "BR",
    "BS",
    "BT",
    "BV",
    "BW",
    "BY",
    "BZ",
    "CA",
    "CC",
    "CD",
    "CF",
    "CG",
    "CH",
    "CI",
    "CK",
    "CL",
    "CM",
    "CN",
    "CO",
    "CR",
    "CU",
    "CV",
    "CW",
    "CX",
    "CY",
    "CZ",
    "DE",
    "DJ",
    "DK",
    "DM",
    "DO",
    "DZ",
    "EC",
    "EE",
    "EG",
    "EH",
    "ER",
    "ES",
    "ET",
    "FI",
    "FJ",
    "FK",
    "FM",
    "FO",
    "FR",
    "GA",
    "GB",
    "GD",
    "GE",
    "GF",
    "GG",
    "GH",
    "GI",
    "GL",
    "GM",
    "GN",
    "GP",
    "GQ",
    "GR",
    "GS",
    "GT",
    "GU",
    "GW",
    "GY",
    "HK",
    "HM",
    "HN",
    "HR",
    "HT",
    "HU",
    "ID",
    "IE",
    "IL",
    "IM",
    "IN",
    "IO",
    "IQ",
    "IR",
    "IS",
    "IT",
    "JE",
    "JM",
    "JO",
    "JP",
    "KE",
    "KG",
    "KH",
    "KI",
    "KM",
    "KN",
    "KP",
    "KR",
    "KW",
    "KY",
    "KZ",
    "LA",
    "LB",
    "LC",
    "LI",
    "LK",
    "LR",
    "LS",
    "LT",
    "LU",
    "LV",
    "LY",
    "MA",
    "MC",
    "MD",
    "ME",
    "MF",
    "MG",
    "MH",
    "MK",
    "ML",
    "MM",
    "MN",
    "MO",
    "MP",
    "MQ",
    "MR",
    "MS",
    "MT",
    "MU",
    "MV",
    "MW",
    "MX",
    "MY",
    "MZ",
    "NA",
    "NC",
    "NE",
    "NF",
    "NG",
    "NI",
    "NL",
    "NO",
    "NP",
    "NR",
    "NU",
    "NZ",
    "OM",
    "PA",
    "PE",
    "PF",
    "PG",
    "PH",
    "PK",
    "PL",
    "PM",
    "PN",
    "PR",
    "PS",
    "PT",
    "PW",
    "PY",
    "QA",
    "RE",
    "RO",
    "RS",
    "RU",
    "RW",
    "SA",
    "SB",
    "SC",
    "SD",
    "SE",
    "SG",
    "SH",
    "SI",
    "SJ",
    "SK",
    "SL",
    "SM",
    "SN",
    "SO",
    "SR",
    "SS",
    "ST",
    "SV",
    "SX",
    "SY",
    "SZ",
    "TC",
    "TD",
    "TF",
    "TG",
    "TH",
    "TJ",
    "TK",
    "TL",
    "TM",
    "TN",
    "TO",
    "TR",
    "TT",
    "TV",
    "TW",
    "TZ",
    "UA",
    "UG",
    "UM",
    "US",
    "UY",
    "UZ",
    "VA",
    "VC",
    "VE",
    "VG",
    "VI",
    "VN",
    "VU",
    "WF",
    "WS",
    "YE",
    "YT",
    "ZA",
    "ZM",
    "ZW",
}

COUNTRY_HEADER_NAMES = (
    "cf-ipcountry",
    "x-vercel-ip-country",
    "cloudfront-viewer-country",
    "x-country-code",
    "x-geo-country",
)

LANGUAGE_COUNTRY_HINTS = {
    "en": "US",
    "es": "ES",
    "pt": "PT",
    "de": "DE",
    "fr": "FR",
    "it": "IT",
    "ja": "JP",
    "ko": "KR",
    "zh": "HK",
    "nl": "NL",
    "sv": "SE",
    "da": "DK",
    "fi": "FI",
    "nb": "NO",
    "nn": "NO",
    "no": "NO",
    "is": "IS",
    "el": "GR",
    "cs": "CZ",
}

AGE_MIN = 13
AGE_MAX = 120

CITY_COUNTRY_ALIASES: dict[str, tuple[str, str]] = {
    "new york": ("New York", "US"), "nyc": ("New York", "US"),
    "los angeles": ("Los Angeles", "US"), "chicago": ("Chicago", "US"),
    "houston": ("Houston", "US"), "phoenix": ("Phoenix", "US"),
    "philadelphia": ("Philadelphia", "US"), "san antonio": ("San Antonio", "US"),
    "san diego": ("San Diego", "US"), "dallas": ("Dallas", "US"),
    "san jose": ("San Jose", "US"), "austin": ("Austin", "US"),
    "miami": ("Miami", "US"), "orlando": ("Orlando", "US"),
    "atlanta": ("Atlanta", "US"), "las vegas": ("Las Vegas", "US"),
    "seattle": ("Seattle", "US"), "boston": ("Boston", "US"),
    "washington": ("Washington", "US"), "texas": ("Texas", "US"),
    "california": ("California", "US"), "florida": ("Florida", "US"),
    "toronto": ("Toronto", "CA"), "vancouver": ("Vancouver", "CA"),
    "montreal": ("Montreal", "CA"), "calgary": ("Calgary", "CA"),
    "ottawa": ("Ottawa", "CA"), "london": ("London", "GB"),
    "manchester": ("Manchester", "GB"), "birmingham": ("Birmingham", "GB"),
    "liverpool": ("Liverpool", "GB"), "glasgow": ("Glasgow", "GB"),
    "berlin": ("Berlin", "DE"), "munich": ("Munich", "DE"),
    "hamburg": ("Hamburg", "DE"), "frankfurt": ("Frankfurt", "DE"),
    "cologne": ("Cologne", "DE"), "paris": ("Paris", "FR"),
    "marseille": ("Marseille", "FR"), "lyon": ("Lyon", "FR"),
    "toulouse": ("Toulouse", "FR"), "rome": ("Rome", "IT"),
    "milan": ("Milan", "IT"), "naples": ("Naples", "IT"),
    "madrid": ("Madrid", "ES"), "barcelona": ("Barcelona", "ES"),
    "valencia": ("Valencia", "ES"), "sevilla": ("Seville", "ES"),
    "seville": ("Seville", "ES"), "malaga": ("Malaga", "ES"),
    "bilbao": ("Bilbao", "ES"), "zaragoza": ("Zaragoza", "ES"),
    "amsterdam": ("Amsterdam", "NL"),
    "rotterdam": ("Rotterdam", "NL"), "brussels": ("Brussels", "BE"),
    "zurich": ("Zurich", "CH"), "geneva": ("Geneva", "CH"),
    "vienna": ("Vienna", "AT"), "dublin": ("Dublin", "IE"),
    "wien": ("Vienna", "AT"), "londres": ("London", "GB"),
    "parigi": ("Paris", "FR"), "roma": ("Rome", "IT"),
    "milano": ("Milan", "IT"), "munchen": ("Munich", "DE"),
    "copenhagen": ("Copenhagen", "DK"), "oslo": ("Oslo", "NO"),
    "stockholm": ("Stockholm", "SE"), "helsinki": ("Helsinki", "FI"),
    "reykjavik": ("Reykjavik", "IS"), "luxembourg": ("Luxembourg", "LU"),
    "lisbon": ("Lisbon", "PT"), "porto": ("Porto", "PT"),
    "athens": ("Athens", "GR"), "prague": ("Prague", "CZ"),
    "tokyo": ("Tokyo", "JP"), "osaka": ("Osaka", "JP"),
    "kyoto": ("Kyoto", "JP"), "sydney": ("Sydney", "AU"),
    "melbourne": ("Melbourne", "AU"), "brisbane": ("Brisbane", "AU"),
    "perth": ("Perth", "AU"), "auckland": ("Auckland", "NZ"),
    "wellington": ("Wellington", "NZ"), "singapore": ("Singapore", "SG"),
    "hong kong": ("Hong Kong", "HK"),
    "mexico city": ("Mexico City", "MX"),
    "cdmx": ("Mexico City", "MX"),
    "ciudad de mexico": ("Mexico City", "MX"),
    "guadalajara": ("Guadalajara", "MX"),
    "monterrey": ("Monterrey", "MX"),
    "puebla": ("Puebla", "MX"),
    "tijuana": ("Tijuana", "MX"),
    "cancun": ("Cancun", "MX"),
    "merida": ("Merida", "MX"),
    "kuala lumpur": ("Kuala Lumpur", "MY"),
    "caracas": ("Caracas", "VE"),
}


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


PHONE_COUNTRY_SOURCE = "telegram_phone_country"
OPERATOR_COUNTRY_SOURCE = "operator_correction"
STATED_COUNTRY_SOURCES = frozenset({"chat_answer", "city_answer", "inbound_user"})


@dataclass(frozen=True)
class CountryWritePlan:
    update_grading: bool
    grading_country_code: str | None
    grading_source: str | None
    stated_country_code: str | None
    stated_source: str | None
    mismatch: bool | None
    phone_country: str | None


def _grading_country_locked(country_source: str | None, phone_country: str | None) -> bool:
    source = str(country_source or "").strip()
    if source == OPERATOR_COUNTRY_SOURCE:
        return True
    if normalize_country_code(phone_country):
        return True
    return source == PHONE_COUNTRY_SOURCE


def plan_country_write(
    *,
    incoming_code: str,
    incoming_source: str,
    existing_grading_code: str | None = None,
    existing_grading_source: str | None = None,
    existing_stated_code: str | None = None,
    existing_phone_country: str | None = None,
) -> CountryWritePlan:
    """Decide what to persist so phone-country grading never yields to a chat claim."""
    incoming = normalize_country_code(incoming_code)
    if not incoming:
        return CountryWritePlan(False, None, None, None, None, None, None)
    source = str(incoming_source or "").strip()
    existing_grading = normalize_country_code(existing_grading_code)
    existing_source = str(existing_grading_source or "").strip()
    existing_stated = normalize_country_code(existing_stated_code)
    existing_phone = normalize_country_code(existing_phone_country)
    if not existing_stated and existing_source in STATED_COUNTRY_SOURCES:
        existing_stated = existing_grading
    if not existing_phone and existing_source == PHONE_COUNTRY_SOURCE:
        existing_phone = existing_grading
    locked = _grading_country_locked(existing_source, existing_phone)

    if source == OPERATOR_COUNTRY_SOURCE:
        stated = existing_stated
        phone = existing_phone
        mismatch = bool((stated and stated != incoming) or (phone and phone != incoming))
        return CountryWritePlan(
            update_grading=True,
            grading_country_code=incoming,
            grading_source=OPERATOR_COUNTRY_SOURCE,
            stated_country_code=None,
            stated_source=None,
            mismatch=mismatch,
            phone_country=None,
        )

    if source == PHONE_COUNTRY_SOURCE:
        if existing_source == OPERATOR_COUNTRY_SOURCE:
            mismatch = bool(existing_grading and incoming != existing_grading)
            return CountryWritePlan(
                update_grading=False,
                grading_country_code=None,
                grading_source=None,
                stated_country_code=None,
                stated_source=None,
                mismatch=mismatch,
                phone_country=incoming,
            )
        stated = existing_stated
        mismatch = bool(stated and stated != incoming)
        return CountryWritePlan(
            update_grading=True,
            grading_country_code=incoming,
            grading_source=PHONE_COUNTRY_SOURCE,
            stated_country_code=None,
            stated_source=None,
            mismatch=mismatch,
            phone_country=incoming,
        )

    if source in STATED_COUNTRY_SOURCES:
        phone = existing_phone or (existing_grading if locked else None)
        mismatch = bool(phone and incoming != phone)
        update_grading = not locked
        return CountryWritePlan(
            update_grading=update_grading,
            grading_country_code=incoming if update_grading else None,
            grading_source=source if update_grading else None,
            stated_country_code=incoming,
            stated_source=source,
            mismatch=mismatch,
            phone_country=None,
        )

    if locked or existing_grading:
        return CountryWritePlan(False, None, None, None, None, None, None)
    return CountryWritePlan(
        update_grading=True,
        grading_country_code=incoming,
        grading_source=source or "unknown",
        stated_country_code=None,
        stated_source=None,
        mismatch=False,
        phone_country=None,
    )


def _fold_ascii_upper(value: str) -> str:
    folded = "".join(
        ch for ch in unicodedata.normalize("NFD", value)
        if unicodedata.category(ch) != "Mn"
    )
    return re.sub(r"\s+", " ", folded.replace("’", "'")).upper()


def normalize_country_code(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    upper = _fold_ascii_upper(raw)
    if upper in {"XX", "UNKNOWN", "ZZ"}:
        return None
    if upper in AMBIGUOUS_BARE_COUNTRY_TOKENS:
        return None
    if upper in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[upper]
    if re.fullmatch(r"[A-Z]{2}", upper):
        if upper in ISO_ALPHA2_COUNTRY_CODES:
            return upper
        return None
    for alias, code in COUNTRY_ALIASES.items():
        if len(alias) > 2 and alias in upper:
            return code
    contextual_code = _country_code_from_context(upper)
    if contextual_code:
        return contextual_code
    return None


def _country_code_from_context(upper: str) -> str | None:
    contexts = (
        r"\b(?:I AM|I'M|IM|AM)\s+(?:FROM|IN)\s+(?:THE\s+)?([A-Z]{2})\b",
        r"\b(?:FROM|IN|LIVE IN|LIVING IN|BASED IN|LOCATED IN)\s+(?:THE\s+)?([A-Z]{2})\b",
        r"\b(?:COUNTRY IS|MY COUNTRY IS)\s+(?:THE\s+)?([A-Z]{2})\b",
    )
    for pattern in contexts:
        match = re.search(pattern, upper)
        if not match:
            continue
        code = match.group(1)
        if code in ISO_ALPHA2_COUNTRY_CODES and code not in AMBIGUOUS_BARE_COUNTRY_TOKENS:
            return code
    return None


def city_country_from_text(text_value: str) -> tuple[str | None, str | None]:
    """Extract a known city or region and its unambiguous country code."""
    folded = "".join(
        ch for ch in unicodedata.normalize("NFD", text_value or "")
        if unicodedata.category(ch) != "Mn"
    )
    normalized = re.sub(r"\s+", " ", folded.strip().lower())
    if not normalized:
        return None, None
    for alias, (city, country_code) in CITY_COUNTRY_ALIASES.items():
        if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", normalized):
            return city, country_code
    return None, None


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
    if not parts:
        return None
    language = normalize_language(parts[0], default="")
    return LANGUAGE_COUNTRY_HINTS.get(language)


def country_from_text_language(text_value: str) -> str | None:
    language = detect_language_from_text(text_value, default="")
    if not language:
        return None
    return LANGUAGE_COUNTRY_HINTS.get(normalize_language(language, default=""))


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
        r"\b(?:i am|i'm|im|age is|aged|tengo|tenho|j'ai|ich bin|sono)\s*(\d{1,3})\b",
        r"\b(\d{1,3})\s*(?:years old|yrs old|yo|y/o|años|anos|ans|jahre(?:\s+alt)?|anni)\b",
        r"(?:我|本人)?\s*(\d{1,3})\s*岁",
    )
    if len(value) <= 24:
        lone = re.fullmatch(r"[^\d]*(\d{1,3})[^\d]*", value)
        if lone:
            age = parse_age_value(lone.group(1))
            if age is not None:
                return age
    for pattern in patterns:
        match = re.search(pattern, value, re.I)
        if match:
            age = parse_age_value(match.group(1))
            if age is not None:
                return age
    birth_year_match = re.search(
        r"\b(?:born\s+in|i\s+was\s+born\s+in|birth\s+year\s+is)\s*(19\d{2}|20\d{2})\b",
        value,
        re.I,
    )
    if birth_year_match:
        year = int(birth_year_match.group(1))
        age = date.today().year - year
        return parse_age_value(age)
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
    try:
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
    except ProgrammingError:
        rollback = getattr(db, "rollback", None)
        if rollback is not None:
            await rollback()
        row = (
            await db.execute(
                text(
                    """
                    SELECT preferences
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
    country_code = data.get("country_code") if hasattr(data, "get") else None
    return profile_completeness(country_code=country_code, preferences=preferences)


async def country_from_recent_user_messages(
    db: AsyncSession,
    *,
    user_id: str,
    limit: int = 5,
) -> str | None:
    result = await db.execute(
        text(
            """
            SELECT m.content
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE c.user_id = CAST(:uid AS uuid)
              AND m.sender_type = 'user'
              AND COALESCE(m.content, '') <> ''
            ORDER BY m.created_at DESC
            LIMIT :limit
            """
        ),
        {"uid": user_id, "limit": limit},
    )
    fetchall = getattr(result, "fetchall", None)
    if fetchall is None:
        return None
    for row in fetchall():
        data = row._mapping if hasattr(row, "_mapping") else row
        content = data["content"] if hasattr(data, "__getitem__") else row[0]
        _, city_code = city_country_from_text(str(content or ""))
        code = city_code or normalize_country_code(content)
        if code:
            return code
    return None


async def _read_country_write_state(
    db: AsyncSession,
    *,
    user_id: str,
) -> tuple[str | None, dict[str, Any]]:
    try:
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
    except ProgrammingError:
        rollback = getattr(db, "rollback", None)
        if rollback is not None:
            await rollback()
        row = (
            await db.execute(
                text(
                    """
                    SELECT preferences
                    FROM user_profiles
                    WHERE user_id = CAST(:uid AS uuid)
                    """
                ),
                {"uid": user_id},
            )
        ).fetchone()
    if not row:
        return None, {}
    data = row._mapping if hasattr(row, "_mapping") else row
    preferences = _as_dict(data["preferences"] if hasattr(data, "__getitem__") else None)
    column_code = data.get("country_code") if hasattr(data, "get") else None
    return normalize_country_code(column_code) or country_from_metadata(preferences), preferences


async def record_stated_location_from_text(
    db: AsyncSession,
    *,
    user_id: str,
    text_value: str,
) -> bool:
    """Store a volunteered city/country without changing phone-country grading."""
    city, country_code = city_country_from_text(text_value)
    country_code = country_code or normalize_country_code(text_value)
    if city and country_code:
        await write_city_country(
            db,
            user_id=user_id,
            city=city,
            country_code=country_code,
        )
        return True
    if country_code:
        await write_country_code(
            db,
            user_id=user_id,
            country_code=country_code,
            source="chat_answer",
        )
        return True
    if not city:
        return False
    await db.execute(
        text(
            """
            UPDATE user_profiles
            SET preferences = jsonb_set(
                    COALESCE(preferences, '{}'::jsonb),
                    '{current_city}',
                    to_jsonb(CAST(:city AS text)),
                    true
                ),
                updated_at = NOW()
            WHERE user_id = CAST(:uid AS uuid)
            """
        ),
        {"uid": user_id, "city": city},
    )
    return True


async def write_city_country(
    db: AsyncSession,
    *,
    user_id: str,
    city: str,
    country_code: str,
    source: str = "city_answer",
) -> None:
    """Persist the city answer and its inferred country as one profile update."""
    await write_country_code(
        db,
        user_id=user_id,
        country_code=country_code,
        source=source,
    )
    await db.execute(
        text(
            """
            UPDATE user_profiles
            SET preferences = jsonb_set(
                    jsonb_set(
                        COALESCE(preferences, '{}'::jsonb),
                        '{current_city}',
                        to_jsonb(CAST(:city AS text)),
                        true
                    ),
                    '{country_from_city}',
                    to_jsonb(CAST(:country_code AS text)),
                    true
                ),
                updated_at = NOW()
            WHERE user_id = CAST(:uid AS uuid)
            """
        ),
        {"uid": user_id, "city": city, "country_code": normalize_country_code(country_code) or country_code},
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
    existing_grading, preferences = await _read_country_write_state(db, user_id=user_id)
    plan = plan_country_write(
        incoming_code=code,
        incoming_source=source,
        existing_grading_code=existing_grading,
        existing_grading_source=str(preferences.get("country_source") or ""),
        existing_stated_code=str(preferences.get("stated_country_code") or "") or None,
        existing_phone_country=str(preferences.get("telegram_phone_country") or "") or None,
    )
    effective_code = plan.grading_country_code or existing_grading or code
    await db.execute(
        text(
            """
            UPDATE telegram_peer_cache pc
            SET metadata = (COALESCE(pc.metadata, '{}'::jsonb) - 'country_tier')
                || jsonb_build_object(
                    'country_code', CAST(:country_code AS text),
                    'country_verified_at', NOW()::text
                )
                || CASE WHEN EXISTS (
                    SELECT 1 FROM app_download_country_routes r
                    WHERE UPPER(r.country_code)=UPPER(CAST(:country_code AS text))
                   ) THEN jsonb_build_object('country_tier','T1') ELSE '{}'::jsonb END,
                updated_at = NOW()
            WHERE pc.user_id = CAST(:uid AS uuid)
            """
        ),
        {"uid": user_id, "country_code": effective_code},
    )
    prefs_patch: dict[str, Any] = {}
    if plan.update_grading and plan.grading_country_code:
        prefs_patch["country_code"] = plan.grading_country_code
        prefs_patch["country_source"] = plan.grading_source
    if plan.stated_country_code:
        prefs_patch["stated_country_code"] = plan.stated_country_code
        prefs_patch["stated_country_source"] = plan.stated_source
    if plan.mismatch is not None:
        prefs_patch["country_mismatch"] = plan.mismatch
    if plan.phone_country:
        prefs_patch["telegram_phone_country"] = plan.phone_country
    grading_code = (plan.grading_country_code or existing_grading or code or "").upper()
    grading_source = str(plan.grading_source or preferences.get("country_source") or source or "")
    if (
        grading_code
        and grading_source not in {"language_fallback", "telegram_language_code"}
        and not preferences.get("t1_identified_at")
    ):
        from services.level_engine import load_t1_countries

        if grading_code in load_t1_countries():
            prefs_patch["t1_identified_at"] = datetime.now(timezone.utc).isoformat()
    if not plan.update_grading and not prefs_patch:
        return
    payload = {
        "uid": user_id,
        "country_code": plan.grading_country_code or code,
        "prefs": json.dumps(prefs_patch, ensure_ascii=False),
    }
    if plan.update_grading and plan.grading_country_code:
        try:
            await db.execute(
                text(
                    """
                    UPDATE user_profiles
                    SET country_code = :country_code,
                        preferences = COALESCE(preferences, '{}'::jsonb) || CAST(:prefs AS jsonb),
                        updated_at = NOW()
                    WHERE user_id = CAST(:uid AS uuid)
                    """
                ),
                payload,
            )
            return
        except ProgrammingError:
            rollback = getattr(db, "rollback", None)
            if rollback is not None:
                await rollback()
    if not prefs_patch:
        return
    await db.execute(
        text(
            """
            UPDATE user_profiles
            SET preferences = COALESCE(preferences, '{}'::jsonb) || CAST(:prefs AS jsonb),
                updated_at = NOW()
            WHERE user_id = CAST(:uid AS uuid)
            """
        ),
        {"uid": user_id, "prefs": payload["prefs"]},
    )


async def clear_profile_intake_pending(
    db: AsyncSession,
    *,
    user_id: str,
) -> None:
    """JSONB || cannot delete keys; remove a stuck intake flag explicitly."""
    await db.execute(
        text(
            """
            UPDATE user_profiles
            SET preferences = COALESCE(preferences, '{}'::jsonb) - 'profile_intake_pending',
                updated_at = NOW()
            WHERE user_id = CAST(:uid AS uuid)
            """
        ),
        {"uid": user_id},
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


def operator_country_link_message(destination_url: str) -> str:
    url = str(destination_url or "").strip()
    if not url:
        return ""
    return (
        "Download this app to video chat with me one-on-one; open here:\n"
        + url
    )


async def apply_operator_country_correction(
    db: AsyncSession,
    *,
    user_id: str,
    country_code: str,
    operator_id: str,
    note: str | None = None,
    external_user_id: str | None = None,
) -> dict[str, Any]:
    """Overwrite grading country with an operator correction and keep prior evidence."""
    code = normalize_country_code(country_code)
    if not code:
        raise ValueError("invalid_country_code")
    previous, preferences = await _read_country_write_state(db, user_id=user_id)
    await write_country_code(
        db,
        user_id=user_id,
        country_code=code,
        source=OPERATOR_COUNTRY_SOURCE,
    )
    extra = {
        "country_corrected_from": previous,
        "country_corrected_by": str(operator_id or ""),
        "country_corrected_at": datetime.now(timezone.utc).isoformat(),
        "country_correction_note": str(note or "").strip()[:200],
    }
    await db.execute(
        text(
            """
            UPDATE user_profiles
            SET preferences = COALESCE(preferences, '{}'::jsonb) || CAST(:prefs AS jsonb),
                updated_at = NOW()
            WHERE user_id = CAST(:uid AS uuid)
            """
        ),
        {"uid": user_id, "prefs": json.dumps(extra, ensure_ascii=False)},
    )
    level: dict[str, Any] | None = None
    if external_user_id:
        try:
            from services.user_level_service import user_level_service

            level = await user_level_service.calculate_and_persist_user_level(
                db,
                user_id=user_id,
                external_user_id=external_user_id,
                country_code=code,
            )
        except Exception:
            level = None
    return {
        "previous_country_code": previous,
        "country_code": code,
        "country_source": OPERATOR_COUNTRY_SOURCE,
        "user_level": (level or {}).get("level"),
        "stated_country_code": normalize_country_code(str(preferences.get("stated_country_code") or "")),
        "telegram_phone_country": normalize_country_code(
            str(preferences.get("telegram_phone_country") or "")
        ),
    }
