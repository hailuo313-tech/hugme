from __future__ import annotations

import asyncio

from services.profile_intake import (
    country_from_headers,
    country_from_locale,
    country_from_metadata,
    country_from_recent_user_messages,
    country_from_text_language,
    extract_age_from_text,
    normalize_country_code,
    profile_completeness,
)


def test_country_normalization_accepts_owner_t1_names_and_codes() -> None:
    assert normalize_country_code("United States") == "US"
    assert normalize_country_code("中国香港") == "HK"
    assert normalize_country_code("new zealand") == "NZ"
    assert normalize_country_code("de") == "DE"


def test_country_detection_prefers_structured_metadata_and_headers() -> None:
    assert country_from_metadata({"country": "Canada"}) == "CA"
    assert country_from_metadata({"country_code": "gb"}) == "GB"
    assert country_from_headers({"cf-ipcountry": "SG"}) == "SG"
    assert country_from_headers({"x-vercel-ip-country": "NL"}) == "NL"


def test_locale_country_hint_is_conservative_for_telegram() -> None:
    assert country_from_locale("de") == "DE"
    assert country_from_locale("en-US") == "US"
    assert country_from_locale("en") == "US"
    assert country_from_locale("es") == "ES"
    assert country_from_locale("pt") == "PT"
    assert country_from_locale("ja") == "JP"


def test_country_hint_from_message_language_defaults_t1_country() -> None:
    assert country_from_text_language("Hola, gracias") == "ES"
    assert country_from_text_language("Olá, obrigado") == "PT"
    assert country_from_text_language("こんにちは") == "JP"
    assert country_from_text_language("안녕하세요") == "KR"


def test_country_from_recent_user_messages_uses_explicit_country_only() -> None:
    class _Result:
        def fetchall(self):
            return [
                {"content": "just to chat really"},
                {"content": "US"},
                {"content": "hello"},
            ]

    class _Db:
        async def execute(self, *_args, **_kwargs):
            return _Result()

    assert (
        asyncio.run(
            country_from_recent_user_messages(
                _Db(),
                user_id="00000000-0000-0000-0000-000000000001",
            )
        )
        == "US"
    )


def test_age_extraction_accepts_explicit_user_age_only() -> None:
    assert extract_age_from_text("24") == 24
    assert extract_age_from_text("I am 35 years old") == 35
    assert extract_age_from_text("我 28 岁") == 28
    assert extract_age_from_text("maybe twenty") is None


def test_profile_completeness_requires_country_and_age() -> None:
    assert profile_completeness(country_code="US", preferences={"age": 22}).complete

    missing_age = profile_completeness(country_code="US", preferences={})
    assert missing_age.complete is False
    assert missing_age.missing_fields == ("age",)

    missing_country = profile_completeness(
        preferences={"ai_extracted_age": {"age": 30}}
    )
    assert missing_country.complete is False
    assert missing_country.missing_fields == ("country_code",)
