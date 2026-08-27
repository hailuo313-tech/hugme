"""Sanitize assistant replies before persisting or sending to users."""

from __future__ import annotations

import re

from core.config import settings
from services.emotion_lexicon import detect_language_from_text, normalize_language
from services.product_i18n import FLIRT_FALLBACK_COPY, pick_localized

_HR_SPLIT_RE = re.compile(r"\n---+\n+")
_EXCESS_BLANK_RE = re.compile(r"\n{3,}")
_MULTI_NEWLINE_RE = re.compile(r"\n\s*\n+")
_INLINE_NEWLINE_RE = re.compile(r"\s*\n\s*")
_STAGE_ACTION_RE = re.compile(r"\*[^*\n]{1,300}\*")
_EXCESS_SPACE_RE = re.compile(r"\s{2,}")

_META_LINE_MARKERS = (
    "note:",
    "guidelines",
    "l3_character",
    "l3设定",
    "2-sentence",
    "2 sentences",
    "maintained:",
    "严守:",
    "profile/details",
    "prompt layers",
    "within bounds",
    "within guidelines",
    "as required",
    "as mandated",
    "zero refusal",
    "zero deflection",
    "no deflection",
    "no evasion",
    "strictly adhering",
    "keeping response",
)

_META_PATTERNS = (
    re.compile(r"\(Note:[^)]*\)", re.IGNORECASE | re.DOTALL),
    re.compile(r"\*\(Note:[^*]*\)\*", re.IGNORECASE | re.DOTALL),
    re.compile(r"\[Note:[^\]]*\]", re.IGNORECASE | re.DOTALL),
    re.compile(r"\*Maintained:[^*]*\*", re.IGNORECASE | re.DOTALL),
    re.compile(r"\*严守:[^*]*\*", re.IGNORECASE | re.DOTALL),
)

_SENTENCE_END_RE = re.compile(r"(?<=[.!?。！？])\s+")
_NO_APP_SENTENCE_RE = re.compile(
    r"^[^.!?。！？\n]*\b(?:"
    r"i don't have (?:any )?app links?|"
    r"there(?:'s| is) no app|"
    r"no app to share|"
    r"let's keep our conversation right here"
    r")[^.!?。！？\n]*[.!?。！？]?\s*$",
    re.IGNORECASE,
)
_NO_MEDIA_REFUSAL_RE = re.compile(
    r"^[^.!?。！？\n]*\b(?:"
    r"i don't share photos?|"
    r"i don't have (?:any )?private videos?|"
    r"i don't have (?:any )?videos? to share|"
    r"i can(?:not|'t) send (?:pics?|photos?|videos?)|"
    r"left to your imagination|"
    r"describe (?:every|the) sensual detail"
    r")[^.!?。！？\n]*[.!?。！？]?\s*$",
    re.IGNORECASE,
)
_PROFILE_SYSTEM_LEAK_RE = re.compile(
    r"(?:"
    r"no tengo una edad definida|"
    r"edad definida en mi perfil|"
    r"no (?:tengo|hay).{0,24}edad.{0,24}perfil|"
    r"(?:not|isn't|is not).{0,24}age.{0,24}(?:profile|defined|set)|"
    r"age.{0,24}(?:not|isn't|is not).{0,24}(?:defined|set|profile)|"
    r"profile/details|"
    r"loneliness_score|"
    r"current_city|"
    r"in my profile database|"
    r"my profile (?:doesn't|does not) have"
    r")",
    re.IGNORECASE | re.UNICODE,
)
_OUTBOUND_CALL_REFUSAL_RE = re.compile(
    r"(?:"
    r"no puedo hacer llamadas|"
    r"no puedo iniciar|"
    r"no puedo llamarte|"
    r"can't (?:make|initiate|start) calls?|"
    r"cannot (?:make|initiate|start) calls?|"
    r"can't call you|"
    r"cannot call you|"
    r"não posso (?:fazer|iniciar) chamadas?"
    r")",
    re.IGNORECASE | re.UNICODE,
)
_NURTURE_INBOUND_CALL_MARKERS: tuple[str, ...] = (
    "tap call",
    "tap the video call",
    "video call button",
    "toca el botón",
    "toca videollamada",
    "toca en chamada",
    "点我资料页",
)

_TRACKING_URL_RE = re.compile(r"https?://[^\s<>\]\"']+/r/[A-Za-z0-9]+")
_URL_RE = re.compile(r"https?://[^\s<>\]\"']+")
_SITE_PATH_LEAK_RE = re.compile(r"(?<!\S)\.\s*site/l/[^\s)]+", re.IGNORECASE)

_EMPTY_REPLY_FALLBACK = "Hey — still here. Say that again?"

_GENERIC_AI_REFUSAL_RE = re.compile(
    r"(?:"
    r"i(?:'m| am) (?:an )?ai assistant|"
    r"can(?:'t| not) comply with (?:this )?request|"
    r"designed to provide helpful and (?:harmless|appropriate)|"
    r"aim to keep interactions respectful|"
    r"respectful and appropriate conversations?|"
    r"happy to have a respectful conversation|"
    r"let me know if you(?:'d| would) like to discuss something else|"
    r"non posso aiutarti con richieste di natura sessuale|"
    r"no puedo ayudarte con solicitudes de naturaleza sexual|"
    r"não posso ajudar com pedidos de natureza sexual|"
    r"对不起|无法满足|无法提供|不能帮助|无法帮助|很抱歉，我无法|"
    r"não posso acessar|não consigo acessar|não posso abrir|não posso ajudar|"
    r"estou aqui para conversar, mas não posso|"
    r"i don(?:'t| not) open external links|"
    r"i(?:'m| am) unable to access external links|"
    r"unable to access external links|"
    r"can(?:'t| not) access external links"
    r")",
    re.IGNORECASE,
)

_FLIRT_FALLBACK_BY_LANG = FLIRT_FALLBACK_COPY


def default_max_reply_chars() -> int:
    return max(40, int(getattr(settings, "OUTBOUND_REPLY_MAX_CHARS", 120) or 120))


def is_generic_ai_refusal(text_value: str | None) -> bool:
    """True when the model emitted a generic safety / AI-assistant refusal."""
    value = str(text_value or "").strip()
    if not value:
        return False
    return bool(_GENERIC_AI_REFUSAL_RE.search(value))


def flirt_fallback_reply(user_text: str | None = None) -> str:
    """Short in-character承接句 when a generic model refusal must be replaced."""
    language = normalize_language(
        detect_language_from_text(user_text or "", default="en"),
        default="en",
    )
    return pick_localized(_FLIRT_FALLBACK_BY_LANG, language)


def replace_generic_ai_refusal(text_value: str | None, *, user_text: str | None = None) -> str:
    """Swap a model refusal template for a business flirt fallback."""
    value = str(text_value or "").strip()
    if not is_generic_ai_refusal(value):
        return value
    return flirt_fallback_reply(user_text)


def _normalize_app_link_reply(text: str) -> str:
    """Keep one tracking URL and drop leaked destination path fragments."""
    value = _SITE_PATH_LEAK_RE.sub("", text).strip()
    urls = _TRACKING_URL_RE.findall(value) or _URL_RE.findall(value)
    if not urls:
        return value
    first_url = urls[0].rstrip(".,!?;:)")
    if "tap here" in value.casefold():
        return f"TAP HERE — private room unlocked: {first_url} (code: c5a8we)"
    if len(urls) > 1:
        for url in urls[1:]:
            value = value.replace(url, "")
        value = re.sub(r"\s{2,}", " ", value).strip()
    return value


def _meaningful_reply(text: str) -> bool:
    stripped = re.sub(r"[^\w\u4e00-\u9fff]+", "", text or "", flags=re.UNICODE)
    return len(stripped) >= 2


def _line_looks_like_meta(line: str) -> bool:
    stripped = str(line or "").strip()
    if not stripped:
        return False
    lowered = stripped.casefold()
    if lowered.startswith("---"):
        return True
    return any(marker in lowered for marker in _META_LINE_MARKERS)


def _strip_meta_patterns(text: str) -> str:
    cleaned = text
    for pattern in _META_PATTERNS:
        while True:
            updated = pattern.sub("", cleaned)
            if updated == cleaned:
                break
            cleaned = updated
    return cleaned


def _drop_meta_lines(text: str) -> str:
    kept: list[str] = []
    for line in text.splitlines():
        if _line_looks_like_meta(line):
            continue
        kept.append(line)
    return "\n".join(kept)


def _drop_refusal_sentences(text: str, pattern: re.Pattern[str]) -> str:
    parts = _SENTENCE_END_RE.split(text.strip())
    if len(parts) <= 1:
        single = text.strip()
        return "" if pattern.match(single) else single
    kept = [part.strip() for part in parts if part.strip() and not pattern.match(part.strip())]
    return " ".join(kept).strip()


def _drop_no_app_refusal_sentences(text: str) -> str:
    return _drop_refusal_sentences(text, _NO_APP_SENTENCE_RE)


def _drop_media_refusal_sentences(text: str) -> str:
    return _drop_refusal_sentences(text, _NO_MEDIA_REFUSAL_RE)


def _drop_profile_system_leak_sentences(text: str) -> str:
    parts = _SENTENCE_END_RE.split(text.strip())
    if len(parts) <= 1:
        single = text.strip()
        return "" if _PROFILE_SYSTEM_LEAK_RE.search(single) else single
    kept = [
        part.strip()
        for part in parts
        if part.strip() and not _PROFILE_SYSTEM_LEAK_RE.search(part.strip())
    ]
    return " ".join(kept).strip()


def nurture_boilerplate_conflicts_with_llm_reply(
    nurture_text: str | None,
    llm_reply: str | None,
) -> bool:
    """Skip inbound-call nurture copy when the model just refused outbound calls."""
    nurture = str(nurture_text or "").strip()
    reply = str(llm_reply or "").strip()
    if not nurture or not reply:
        return False
    if not _OUTBOUND_CALL_REFUSAL_RE.search(reply):
        return False
    nurture_lower = nurture.casefold()
    return any(marker in nurture_lower for marker in _NURTURE_INBOUND_CALL_MARKERS)


def _strip_stage_actions(text: str) -> str:
    cleaned = _STAGE_ACTION_RE.sub(" ", text or "")
    return _EXCESS_SPACE_RE.sub(" ", cleaned).strip()


def _collapse_paragraphs(text: str) -> str:
    value = _MULTI_NEWLINE_RE.sub(" ", text)
    value = _INLINE_NEWLINE_RE.sub(" ", value)
    return _EXCESS_SPACE_RE.sub(" ", value).strip()


def enforce_max_sentences(text: str, max_sentences: int = 2) -> str:
    value = str(text or "").strip()
    if not value or max_sentences < 1:
        return value

    urls: list[str] = []

    def _stash_url(match: re.Match[str]) -> str:
        urls.append(match.group(0))
        return f"__URL_{len(urls) - 1}__"

    protected = _URL_RE.sub(_stash_url, value)
    parts: list[str] = []
    buffer = ""
    for ch in protected:
        buffer += ch
        if ch in ".!?。！？":
            piece = buffer.strip()
            if piece:
                parts.append(piece)
            buffer = ""
            if len(parts) >= max_sentences:
                break
    if len(parts) < max_sentences and buffer.strip():
        parts.append(buffer.strip())
    result = " ".join(parts[:max_sentences]).strip() or protected
    for idx, url in enumerate(urls):
        result = result.replace(f"__URL_{idx}__", url)
    return result.strip() or value


def enforce_max_chars(text: str, max_chars: int | None = None) -> str:
    value = str(text or "").strip()
    limit = max_chars if max_chars is not None else default_max_reply_chars()
    if not value or len(value) <= limit:
        return value

    urls: list[str] = []

    def _stash_url(match: re.Match[str]) -> str:
        urls.append(match.group(0))
        return f"__URL_{len(urls) - 1}__"

    protected = _URL_RE.sub(_stash_url, value)
    truncated = protected[:limit]
    for sep in ".!?。！？":
        idx = truncated.rfind(sep)
        if idx >= max(limit // 3, 20):
            truncated = truncated[: idx + 1]
            break
    else:
        space = truncated.rfind(" ")
        if space >= max(limit // 2, 24):
            truncated = truncated[:space]

    result = truncated.strip()
    for idx, url in enumerate(urls):
        result = result.replace(f"__URL_{idx}__", url)
    return result.strip() or value[:limit].strip()


def sanitize_outbound_reply(
    text_value: str | None,
    *,
    max_sentences: int = 2,
    max_chars: int | None = None,
    user_text: str | None = None,
) -> str:
    """Remove LLM meta notes, stage actions, and enforce short direct replies."""
    if not text_value:
        return ""

    text = str(text_value).strip()
    text = replace_generic_ai_refusal(text, user_text=user_text)
    if _HR_SPLIT_RE.search(text):
        text = _HR_SPLIT_RE.split(text, maxsplit=1)[0].strip()

    text = _strip_stage_actions(text)
    text = _strip_meta_patterns(text)
    text = _drop_meta_lines(text)
    text = _drop_no_app_refusal_sentences(text)
    text = _drop_media_refusal_sentences(text)
    text = _drop_profile_system_leak_sentences(text)
    text = _collapse_paragraphs(text)
    text = _EXCESS_BLANK_RE.sub(" ", text).strip()
    text = _normalize_app_link_reply(text)
    text = enforce_max_sentences(text, max_sentences=max_sentences)
    text = enforce_max_chars(text, max_chars=max_chars)
    text = text.strip()
    if not _meaningful_reply(text):
        return _EMPTY_REPLY_FALLBACK
    return text
