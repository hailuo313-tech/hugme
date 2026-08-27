from __future__ import annotations

from services.emotion_lexicon import SUPPORTED_LANGUAGES
from services.product_i18n import (
    ASSET_IMAGE_KEYWORDS,
    ASSET_REQUEST_TERMS,
    ASSET_VIDEO_KEYWORDS,
    FLIRT_FALLBACK_COPY,
    NURTURE_ACCEPT_ACK_COPY,
    NURTURE_DELAY_FOLLOWUP_COPY,
    NURTURE_NEED_HELP_COPY,
    NURTURE_VIDEO_ROUND_COPY,
    PRODUCT_LANGUAGE_CODES,
    PROFILE_INTAKE_COPY,
    VIDEO_CALL_KEYWORDS,
    normalize_product_language,
    pick_localized,
    profile_intake_text,
)


def test_product_language_codes_cover_supported_languages():
    assert set(PRODUCT_LANGUAGE_CODES) == SUPPORTED_LANGUAGES
    assert len(PRODUCT_LANGUAGE_CODES) == 17


def test_all_profile_intake_languages_present():
    for lang in SUPPORTED_LANGUAGES:
        row = PROFILE_INTAKE_COPY[lang]
        assert row["country_question"]
        assert row["age_question"]


def test_all_nurture_copy_tables_cover_17_languages():
    for table in (
        NURTURE_NEED_HELP_COPY,
        NURTURE_ACCEPT_ACK_COPY,
        NURTURE_DELAY_FOLLOWUP_COPY,
        FLIRT_FALLBACK_COPY,
    ):
        assert set(table.keys()) == SUPPORTED_LANGUAGES

    for round_num in (1, 2, 3):
        assert set(NURTURE_VIDEO_ROUND_COPY[round_num].keys()) == SUPPORTED_LANGUAGES


def test_normalize_product_language_keeps_supported_codes():
    assert normalize_product_language("es-MX") == "es"
    assert normalize_product_language("de-DE") == "de"
    assert normalize_product_language("xx") == "en"


def test_pick_localized_falls_back_to_english():
    assert pick_localized(NURTURE_NEED_HELP_COPY, "de").startswith("Tippe")
    assert pick_localized(NURTURE_NEED_HELP_COPY, "xx") == NURTURE_NEED_HELP_COPY["en"]


def test_profile_intake_text_uses_detected_language():
    text = profile_intake_text("age_question", None, user_text="Gracias. ¿Cuántos años tienes?")
    assert "años" in text.lower()


def test_merged_keyword_packs_include_spanish_and_german():
    joined = " ".join(ASSET_IMAGE_KEYWORDS).casefold()
    assert "fotos" in joined
    assert "nackt" in joined
    assert "pošli" in " ".join(ASSET_REQUEST_TERMS).casefold()
    assert "videollamada" in " ".join(VIDEO_CALL_KEYWORDS).casefold()
    assert "videopuhelu" in " ".join(VIDEO_CALL_KEYWORDS).casefold()
