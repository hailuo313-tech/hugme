from __future__ import annotations

from services.emotion_lexicon import SUPPORTED_LANGUAGES
from services.app_download_conversion import _keyword_matches, _normalize_keyword_text
from services.call_broadcast.keywords import is_video_call_request, matched_video_call_keyword
from services.product_i18n import (
    ASSET_IMAGE_KEYWORDS,
    ASSET_REQUEST_TERMS,
    ASSET_VIDEO_KEYWORDS,
    FLIRT_FALLBACK_COPY,
    MEETUP_DEFER_COPY,
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

TRANSLATED_KEYWORD_SMOKE_CASES = {
    "zh": {
        "image": ("照片", "发照片"),
        "video": ("短片", "想看短片"),
        "request": "发",
        "call": ("视频通话", "可以视频通话吗"),
    },
    "es": {
        "image": ("fotos", "mándame fotos"),
        "video": ("videito", "mándame un videito"),
        "request": "mándame",
        "call": ("videollamada", "quiero una videollamada"),
    },
    "pt": {
        "image": ("foto sua", "me manda uma foto sua"),
        "video": ("vídeo", "me manda um vídeo"),
        "request": "me manda",
        "call": ("videochamada", "quero uma videochamada"),
    },
    "ja": {
        "image": ("写真", "写真を送って"),
        "video": ("動画", "動画を見せて"),
        "request": "送って",
        "call": ("ビデオ通話", "ビデオ通話したい"),
    },
    "ko": {
        "image": ("사진", "사진 보내줘"),
        "video": ("영상", "영상 보여줘"),
        "request": "보내줘",
        "call": ("영상통화", "영상통화 하자"),
    },
    "fr": {
        "image": ("photo", "envoie une photo"),
        "video": ("vidéo", "envoie une vidéo"),
        "request": "envoie",
        "call": ("appel vidéo", "je veux un appel vidéo"),
    },
    "de": {
        "image": ("foto", "schick mir ein foto"),
        "video": ("video", "schick mir ein video"),
        "request": "schick",
        "call": ("videoanruf", "ich will einen videoanruf"),
    },
    "it": {
        "image": ("foto", "mandami una foto"),
        "video": ("video", "mandami un video"),
        "request": "mandami",
        "call": ("videochiamata", "voglio una videochiamata"),
    },
    "nl": {
        "image": ("foto", "stuur me een foto"),
        "video": ("video", "stuur me een video"),
        "request": "stuur",
        "call": ("videogesprek", "ik wil een videogesprek"),
    },
    "sv": {
        "image": ("foto", "skicka en foto"),
        "video": ("klipp", "skicka ett klipp"),
        "request": "skicka",
        "call": ("videosamtal", "jag vill ha ett videosamtal"),
    },
    "da": {
        "image": ("foto", "send mig et foto"),
        "video": ("klip", "send mig et klip"),
        "request": "send mig",
        "call": ("videoopkald", "jeg vil have et videoopkald"),
    },
    "no": {
        "image": ("bilde", "send meg et bilde"),
        "video": ("klipp", "send meg et klipp"),
        "request": "send meg",
        "call": ("videosamtale", "jeg vil ha en videosamtale"),
    },
    "fi": {
        "image": ("kuva", "lähetä kuva"),
        "video": ("video", "lähetä video"),
        "request": "lähetä",
        "call": ("videopuhelu", "haluan videopuhelu"),
    },
    "is": {
        "image": ("mynd", "sendu mynd"),
        "video": ("myndband", "sendu myndband"),
        "request": "sendu",
        "call": ("myndsímtal", "ég vil myndsímtal"),
    },
    "el": {
        "image": ("φωτογραφία", "στείλε φωτογραφία"),
        "video": ("βίντεο", "στείλε βίντεο"),
        "request": "στείλε",
        "call": ("βιντεοκλήση", "θέλω βιντεοκλήση"),
    },
    "cs": {
        "image": ("fotku", "pošli fotku"),
        "video": ("video", "pošli video"),
        "request": "pošli",
        "call": ("videohovor", "chci videohovor"),
    },
}


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
        MEETUP_DEFER_COPY,
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


def test_translated_keyword_packs_cover_all_non_english_languages():
    assert set(TRANSLATED_KEYWORD_SMOKE_CASES) == SUPPORTED_LANGUAGES - {"en"}
    image_words = {_normalize_keyword_text(value) for value in ASSET_IMAGE_KEYWORDS}
    video_words = {_normalize_keyword_text(value) for value in ASSET_VIDEO_KEYWORDS}
    request_words = {_normalize_keyword_text(value) for value in ASSET_REQUEST_TERMS}
    call_words = {_normalize_keyword_text(value) for value in VIDEO_CALL_KEYWORDS}

    for case in TRANSLATED_KEYWORD_SMOKE_CASES.values():
        assert _normalize_keyword_text(case["image"][0]) in image_words
        assert _normalize_keyword_text(case["video"][0]) in video_words
        assert _normalize_keyword_text(case["request"]) in request_words
        assert _normalize_keyword_text(case["call"][0]) in call_words


def test_translated_asset_keywords_match_real_request_phrases():
    for case in TRANSLATED_KEYWORD_SMOKE_CASES.values():
        image_keyword, image_phrase = case["image"]
        video_keyword, video_phrase = case["video"]
        assert _keyword_matches(
            _normalize_keyword_text(image_phrase),
            image_keyword,
            asset_kind="image",
        )
        assert _keyword_matches(
            _normalize_keyword_text(video_phrase),
            video_keyword,
            asset_kind="video",
        )


def test_translated_video_call_keywords_match_real_request_phrases():
    for case in TRANSLATED_KEYWORD_SMOKE_CASES.values():
        call_keyword, call_phrase = case["call"]
        assert is_video_call_request(call_phrase)
        assert matched_video_call_keyword(call_phrase) == call_keyword
