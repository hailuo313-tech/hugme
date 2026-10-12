#!/usr/bin/env python3
"""Production/local verification for 17-lang packs and inbound coalesce."""

from __future__ import annotations

from services.emotion_lexicon import SUPPORTED_LANGUAGES
from services.product_i18n import (
    FLIRT_FALLBACK_COPY,
    NURTURE_ACCEPT_ACK_COPY,
    NURTURE_DELAY_FOLLOWUP_COPY,
    NURTURE_NEED_HELP_COPY,
    NURTURE_VIDEO_ROUND_COPY,
    PROFILE_INTAKE_COPY,
)
from services.app_download_conversion import _keyword_matches, _normalize_keyword_text
from services.call_broadcast.keywords import is_video_call_request
from services.nurture_reply_handler import classify_nurture_reply_intent
from services.inbound_reply_coalescer import coalesce_debounce_seconds, merge_coalesced_user_text


def main() -> int:
    exit_code = 0
    results: list[tuple[str, str, object]] = []

    missing: list[str] = []
    for lang in sorted(SUPPORTED_LANGUAGES):
        if lang not in PROFILE_INTAKE_COPY:
            missing.append(f"{lang}:profile")
        elif len(PROFILE_INTAKE_COPY[lang]) < 4:
            missing.append(f"{lang}:profile_keys")
        for tname, table in (
            ("need_help", NURTURE_NEED_HELP_COPY),
            ("accept", NURTURE_ACCEPT_ACK_COPY),
            ("delay", NURTURE_DELAY_FOLLOWUP_COPY),
            ("flirt", FLIRT_FALLBACK_COPY),
        ):
            if not table.get(lang):
                missing.append(f"{lang}:{tname}")
        for r in (1, 2, 3):
            if not NURTURE_VIDEO_ROUND_COPY[r].get(lang):
                missing.append(f"{lang}:round{r}")
    results.append(
        (
            "A_TABLE_17LANG",
            "PASS" if not missing else "FAIL",
            missing or len(SUPPORTED_LANGUAGES),
        )
    )

    samples = {
        "en": ("send me your photos", "photo", "send me a video", "video"),
        "zh": ("发我你的照片", "照片", "发个视频", "视频"),
        "es": ("mándame fotos", "fotos", "mándame un video", "video"),
        "pt": ("me manda fotos", "fotos", "me manda um vídeo", "vídeo"),
        "ja": ("写真送って", "写真", "動画送って", "動画"),
        "ko": ("사진 보내줘", "사진", "영상 보내줘", "영상"),
        "fr": ("envoie tes photos", "photo", "envoie une vidéo", "vidéo"),
        "de": ("schick mir fotos", "foto", "schick mir ein video", "video"),
        "it": ("mandami le foto", "foto", "mandami un video", "video"),
        "nl": ("stuur me fotos", "foto", "stuur me een video", "video"),
        "sv": ("skicka foton", "foto", "skicka en video", "video"),
        "da": ("send billeder", "foto", "send en video", "video"),
        "no": ("send bilder", "foto", "send en video", "video"),
        "fi": ("lähetä kuvia", "kuva", "lähetä video", "video"),
        "is": ("sendu myndir", "mynd", "sendu myndband", "myndband"),
        "el": ("στείλε φωτογραφίες", "φωτο", "στείλε βίντεο", "βίντεο"),
        "cs": ("pošli fotky", "foto", "pošli video", "video"),
    }
    kw_fail: list[str] = []
    for lang, (itxt, ikw, vtxt, vkw) in samples.items():
        if not _keyword_matches(_normalize_keyword_text(itxt), ikw, asset_kind="image"):
            kw_fail.append(f"{lang}:image")
        if not _keyword_matches(_normalize_keyword_text(vtxt), vkw, asset_kind="video"):
            kw_fail.append(f"{lang}:video")
    results.append(("D_KEYWORD_17LANG", "PASS" if not kw_fail else "FAIL", kw_fail))

    vc_samples = {
        "en": "video call",
        "zh": "视频通话",
        "es": "videollamada",
        "pt": "chamada de vídeo",
        "ja": "ビデオ通話",
        "ko": "영상통화",
        "fr": "appel vidéo",
        "de": "videoanruf",
        "it": "videochiamata",
        "nl": "videogesprek",
        "sv": "videosamtal",
        "da": "videoopkald",
        "no": "videosamtale",
        "fi": "videopuhelu",
        "is": "myndsímtal",
        "el": "βιντεοκλήση",
        "cs": "videohovor",
    }
    vc_fail = [lang for lang, txt in vc_samples.items() if not is_video_call_request(txt)]
    results.append(("E_VIDEO_CALL_17LANG", "PASS" if not vc_fail else "FAIL", vc_fail))

    nurture_ok = (
        classify_nurture_reply_intent("sí, videollamada") == "accept_call"
        and classify_nurture_reply_intent("¿Me puedes hacer una videollamada?") == "open_chat"
    )
    results.append(("B_NURTURE_CLASSIFY", "PASS" if nurture_ok else "FAIL", nurture_ok))

    markers = {
        "en": "country",
        "zh": "国家",
        "es": "país",
        "pt": "país",
        "ja": "国",
        "ko": "나라",
        "fr": "pays",
        "de": "Land",
        "it": "paese",
        "nl": "land",
        "sv": "land",
        "da": "land",
        "no": "land",
        "fi": "maassa",
        "is": "landi",
        "el": "χώρα",
        "cs": "zemi",
    }
    prof_fail = [
        lang
        for lang, marker in markers.items()
        if marker.lower() not in PROFILE_INTAKE_COPY[lang]["country_question"].lower()
    ]
    results.append(("C_PROFILE_COUNTRY", "PASS" if not prof_fail else "FAIL", prof_fail))

    merged = merge_coalesced_user_text(["Hola", "Cuántos años tienes?"])
    results.append(("C2_MERGE_TEXT", "PASS" if "\n" in merged else "FAIL", merged))
    results.append(("COALESCE_SECONDS", "INFO", coalesce_debounce_seconds()))

    for name, status, detail in results:
        print(f"{name}\t{status}\t{detail}")
        if status == "FAIL":
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
