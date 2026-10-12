"""High-priority user intent detection for orchestrator routing."""

from __future__ import annotations


def _normalize_keyword_text(value: str | None) -> str:
    return " ".join(str(value or "").casefold().replace("'", "'").split())


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def is_explicit_app_link_request(user_text: str | None) -> bool:
    text = _normalize_keyword_text(user_text)
    if not text:
        return False
    return _has_any(
        text,
        (
            "app link",
            "download app link",
            "download app",
            "download link",
            "send me the app link",
            "send me the link",
            "send me app link",
            "send app link",
            "open app link",
            "tap here",
            "grab it",
            "give me the link",
            "give me link",
            "where is the link",
            "链接",
            "发链接",
            "给我链接",
            "下载链接",
            "app下载",
        ),
    )


def is_broken_link_report(user_text: str | None) -> bool:
    text = _normalize_keyword_text(user_text)
    if not text:
        return False
    return _has_any(
        text,
        (
            "link does not open",
            "link doesn't open",
            "link wont open",
            "link won't open",
            "link not open",
            "link does not work",
            "link doesn't work",
            "nothing happened",
            "didn't open",
            "doesnt open",
            "doesn't open",
            "clicked it but",
            "i clicked it",
            "打不开",
            "链接打不开",
            "链接无效",
            "链接没用",
            "点了没反应",
        ),
    )


def is_serious_conversation_request(user_text: str | None) -> bool:
    text = _normalize_keyword_text(user_text)
    if not text:
        return False
    return _has_any(
        text,
        (
            "serious conversation",
            "want a serious",
            "认真聊",
            "严肃",
        ),
    )


def is_bot_suspicion_request(user_text: str | None) -> bool:
    text = _normalize_keyword_text(user_text)
    if not text:
        return False
    return _has_any(
        text,
        (
            "sound like a bot",
            "like a bot",
            "you sound like",
            "are you a bot",
            "you're a bot",
            "youre a bot",
            "像机器人",
            "是机器人",
        ),
    )


def is_trust_reassurance_request(user_text: str | None) -> bool:
    text = _normalize_keyword_text(user_text)
    if not text:
        return False
    if is_bot_suspicion_request(text):
        return True
    return _has_any(
        text,
        (
            "are you real",
            "real person",
            "is this real",
            "is the app safe",
            "is it safe",
            "app safe",
            "is this safe",
            "scam",
            "fake",
            "bot?",
            "a bot",
            "真人",
            "真的吗",
            "安全吗",
            "是不是骗子",
        ),
    )


def is_media_asset_request(user_text: str | None) -> bool:
    """True when user wants a photo/video file (not a live video call)."""
    from services.app_download_conversion import _detect_whitelist_asset_kind

    return _detect_whitelist_asset_kind(user_text) is not None


def should_skip_download_nudge(user_text: str | None) -> bool:
    text = _normalize_keyword_text(user_text)
    if not text:
        return False
    if is_serious_conversation_request(text):
        return True
    if is_trust_reassurance_request(text):
        return True
    if is_media_asset_request(text):
        return True
    return _has_any(
        text,
        (
            "don't want to download",
            "dont want to download",
            "no download",
            "not downloading",
            "不想下载",
            "不下载",
            "i don't want to download anything",
        ),
    )


def bypasses_link_cooldown(user_text: str | None) -> bool:
    """Intents that must still run script routing during per-conversation link cooldown."""
    return (
        forces_app_download_script(user_text)
        or is_media_asset_request(user_text)
        or is_trust_reassurance_request(user_text)
        or is_serious_conversation_request(user_text)
    )


def forces_app_download_script(user_text: str | None) -> bool:
    return is_explicit_app_link_request(user_text) or is_broken_link_report(user_text)
