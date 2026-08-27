from __future__ import annotations

import re
from typing import Final

SUPPORTED_LANGUAGES: Final[set[str]] = {
    "zh",
    "en",
    "es",
    "pt",
    "ja",
    "ko",
    "fr",
    "de",
    "it",
    "nl",
    "sv",
    "da",
    "no",
    "fi",
    "is",
    "el",
    "cs",
}

LANGUAGE_NAMES: Final[dict[str, str]] = {
    "zh": "Chinese",
    "en": "English",
    "es": "Spanish",
    "pt": "Portuguese",
    "ja": "Japanese",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "nl": "Dutch",
    "sv": "Swedish",
    "da": "Danish",
    "no": "Norwegian",
    "fi": "Finnish",
    "is": "Icelandic",
    "el": "Greek",
    "cs": "Czech",
}

TAG_WEIGHTS: Final[dict[str, float]] = {
    "lonely": 10.0,
    "anxious": 9.0,
    "sad": 8.0,
    "angry": 3.0,
    "happy": -8.0,
    "calm": -6.0,
    "excited": -4.0,
}

# Tags are ordered by product importance. Inference returns the first 3 distinct tags.
EMOTION_LEXICON: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "lonely": {
        "zh": ("孤独", "寂寞", "孤单", "没人陪", "一个人很", "好想有人"),
        "en": ("lonely", "so lonely", "feel isolated", "all alone", "no one is here"),
        "es": ("solo", "sola", "soledad", "me siento aislado", "me siento aislada"),
        "fr": ("seul", "seule", "solitude", "je me sens isolé", "je me sens isolée"),
        "de": ("einsam", "allein", "isoliert", "fühle mich verlassen"),
    },
    "sad": {
        "zh": ("难过", "伤心", "想哭", "好难受", "低落", "崩溃"),
        "en": ("i'm sad", "feeling sad", "so sad", "depressed", "heartbroken"),
        "es": ("triste", "deprimido", "deprimida", "quiero llorar", "destrozado"),
        "fr": ("triste", "déprimé", "déprimée", "envie de pleurer", "coeur brisé"),
        "de": ("traurig", "deprimiert", "ich will weinen", "gebrochenes herz"),
    },
    "anxious": {
        "zh": ("焦虑", "担心", "心慌", "睡不着", "紧张", "害怕"),
        "en": ("panic", "anxious", "worried", "nervous", "can't sleep"),
        "es": ("ansioso", "ansiosa", "preocupado", "preocupada", "nervioso", "nerviosa"),
        "fr": ("anxieux", "anxieuse", "inquiet", "inquiète", "nerveux", "nerveuse"),
        "de": ("ängstlich", "besorgt", "nervös", "panik", "kann nicht schlafen"),
    },
    "angry": {
        "zh": ("生气", "愤怒", "烦死了", "气死", "讨厌"),
        "en": ("angry", "furious", "pissed", "mad at"),
        "es": ("enojado", "enojada", "furioso", "furiosa", "me molesta"),
        "fr": ("en colère", "furieux", "furieuse", "ça m'énerve"),
        "de": ("wütend", "sauer", "verärgert", "macht mich fertig"),
    },
    "happy": {
        "zh": ("开心", "高兴", "快乐", "太好啦", "太棒了"),
        "en": ("happy", "so happy", "glad", "feeling great"),
        "es": ("feliz", "contento", "contenta", "me alegra", "genial"),
        "fr": ("heureux", "heureuse", "content", "contente", "ça me rend heureux"),
        "de": ("glücklich", "froh", "freut mich", "fühle mich gut"),
    },
    "calm": {
        "zh": ("还好", "平静", "淡定", "放松一下"),
        "en": ("calm", "relaxed", "chill", "i'm okay"),
        "es": ("tranquilo", "tranquila", "relajado", "relajada", "estoy bien"),
        "fr": ("calme", "détendu", "détendue", "ça va"),
        "de": ("ruhig", "entspannt", "alles gut", "mir geht es okay"),
    },
    "excited": {
        "zh": ("兴奋", "激动", "期待"),
        "en": ("excited", "can't wait", "pumped", "looking forward"),
        "es": ("emocionado", "emocionada", "entusiasmado", "entusiasmada", "no puedo esperar"),
        "fr": ("excité", "excitée", "enthousiaste", "j'ai hâte"),
        "de": ("aufgeregt", "begeistert", "ich freue mich", "kann es kaum erwarten"),
    },
}

_LANG_ALIASES: Final[dict[str, str]] = {
    "zh-cn": "zh",
    "zh-hans": "zh",
    "zh": "zh",
    "cn": "zh",
    "en-us": "en",
    "en-gb": "en",
    "en": "en",
    "es-es": "es",
    "es-mx": "es",
    "es-us": "es",
    "es": "es",
    "pt-pt": "pt",
    "pt-br": "pt",
    "pt": "pt",
    "ja-jp": "ja",
    "jp": "ja",
    "ja": "ja",
    "ko-kr": "ko",
    "kr": "ko",
    "ko": "ko",
    "fr-fr": "fr",
    "fr-ca": "fr",
    "fr": "fr",
    "de-de": "de",
    "de-at": "de",
    "de-ch": "de",
    "de": "de",
    "it-it": "it",
    "it": "it",
    "nl-nl": "nl",
    "nl-be": "nl",
    "nl": "nl",
    "sv-se": "sv",
    "sv": "sv",
    "da-dk": "da",
    "da": "da",
    "nb-no": "no",
    "nn-no": "no",
    "no-no": "no",
    "nb": "no",
    "nn": "no",
    "no": "no",
    "fi-fi": "fi",
    "fi": "fi",
    "is-is": "is",
    "is": "is",
    "el-gr": "el",
    "el": "el",
    "cs-cz": "cs",
    "cs": "cs",
}

_LANG_HINTS: Final[dict[str, tuple[str, ...]]] = {
    "es": (
        " que ", " estoy ", " siento ", " hola ", " gracias ", " solo", " sola", " feliz",
        " quiero ", " donde ", " mandame ", " mándame ", " fotos ", " foto ", " imagen ",
        " puedes ", " tienes ", " cuantos ", " cuántos ", " años ", " edad ", " mi vida ",
    ),
    "pt": (
        " que ", " estou ", " sinto ", " olá ", " ola ", " obrigado ", " obrigada ",
        " sozinho", " sozinha", " feliz", " quero ", " cadê ", " cade ", " você ", " voce ",
        " sexo ", " agora ", " chamada ", " vídeo ", " video ",
    ),
    "fr": (" je ", " suis ", " très ", " merci ", " bonjour ", " seul", " seule", " triste", " veux ", " photo ", " vidéo "),
    "de": (" ich ", " bin ", " sehr ", " danke ", " hallo ", " einsam", " traurig", " glücklich", " möchte ", " foto ", " video "),
    "it": (" che ", " sono ", " ciao ", " grazie ", " voglio ", " triste", " felice", " foto ", " video "),
    "nl": (" ik ", " ben ", " hallo ", " dank je ", " bedankt ", " wil ", " verdrietig", " foto ", " video "),
    "sv": (" jag ", " är ", " hej ", " tack ", " vill ", " ledsen", " foto ", " video "),
    "da": (" jeg ", " er ", " hej ", " tak ", " vil ", " trist", " foto ", " video "),
    "no": (" jeg ", " er ", " hei ", " takk ", " vil ", " trist", " foto ", " video "),
    "fi": (" minä ", " olen ", " hei ", " kiitos ", " haluan ", " surullinen", " kuva ", " video "),
    "is": (" ég ", " er ", " hæ ", " takk ", " vil ", " leiður", " mynd ", " myndband "),
    "el": (" είμαι ", " γεια ", " ευχαριστώ ", " θέλω ", " φωτο ", " βίντεο "),
    "cs": (" jsem ", " ahoj ", " děkuji ", " chci ", " smutný", " foto ", " video "),
    "ja": (" です ", " ます ", " こんにちは ", " ありがとう ", " 写真 ", " 動画 "),
    "ko": (" 입니다 ", " 합니다 ", " 안녕 ", " 감사 ", " 사진 ", " 영상 "),
}


def normalize_language(value: str | None, default: str = "zh") -> str:
    key = (value or "").strip().lower().replace("_", "-")
    if not key:
        return default
    return _LANG_ALIASES.get(key, _LANG_ALIASES.get(key.split("-")[0], default))


def language_name(code: str | None) -> str:
    normalized = normalize_language(code)
    return LANGUAGE_NAMES.get(normalized, LANGUAGE_NAMES["zh"])


def detect_language_from_text(text_value: str, default: str = "zh") -> str:
    text_value = (text_value or "").strip()
    if not text_value:
        return default
    if re.search(r"[\u3040-\u30ff]", text_value):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", text_value):
        return "ko"
    if re.search(r"[\u0370-\u03ff]", text_value):
        return "el"
    if re.search(r"[\u4e00-\u9fff]", text_value):
        return "zh"
    padded = f" {re.sub(r'[^\w]+', ' ', text_value.lower(), flags=re.UNICODE)} "
    for lang, hints in _LANG_HINTS.items():
        if any(hint in padded for hint in hints):
            return lang
    return "en" if re.search(r"[a-zA-Z]", text_value) else default


def keyword_in_text(text_value: str, keyword: str) -> bool:
    key = keyword.strip()
    if not key:
        return False
    if key.isascii():
        return key.lower() in text_value.lower()
    return key in text_value


def infer_emotion_tags(text_value: str, *, max_tags: int = 3) -> list[str]:
    if not text_value or not text_value.strip():
        return []
    normalized = re.sub(r"\s+", " ", text_value.strip())
    picked: list[str] = []
    seen: set[str] = set()
    for tag, by_language in EMOTION_LEXICON.items():
        if tag in seen:
            continue
        for keywords in by_language.values():
            if any(keyword_in_text(normalized, keyword) for keyword in keywords):
                picked.append(tag)
                seen.add(tag)
                break
        if len(picked) >= max_tags:
            break
    return picked
