"""MTProto / Telethon 环境就绪检查（C-03）。

W2 接入 Telethon 前仅做配置校验，不发起网络连接。
"""

from __future__ import annotations

from core.config import settings

_PLACEHOLDER_FRAGMENTS = (
    "change_me",
    "your_api_hash",
    "xxx",
    "12345678",
)


def _is_placeholder(value: str | None) -> bool:
    if not value or not str(value).strip():
        return True
    lowered = str(value).strip().lower()
    return any(p in lowered for p in _PLACEHOLDER_FRAGMENTS)


def mtproto_env_status() -> tuple[bool, list[str]]:
    """返回 (是否就绪, 缺失或无效项说明列表)。"""
    issues: list[str] = []

    if settings.TELEGRAM_API_ID is None:
        issues.append("TELEGRAM_API_ID is not set")
    elif settings.TELEGRAM_API_ID <= 0:
        issues.append("TELEGRAM_API_ID must be a positive integer")

    if _is_placeholder(settings.TELEGRAM_API_HASH):
        issues.append("TELEGRAM_API_HASH is missing or still a placeholder")

    if _is_placeholder(settings.TELEGRAM_SESSION_FERNET_KEY):
        issues.append("TELEGRAM_SESSION_FERNET_KEY is missing or still a placeholder")
    else:
        try:
            from cryptography.fernet import Fernet

            Fernet(settings.TELEGRAM_SESSION_FERNET_KEY.encode("ascii"))
        except Exception as exc:  # noqa: BLE001 — surface config error to operator
            issues.append(f"TELEGRAM_SESSION_FERNET_KEY is not a valid Fernet key: {exc}")

    has_strings = bool(settings.TELEGRAM_SESSION_STRINGS and settings.TELEGRAM_SESSION_STRINGS.strip())
    has_dir = bool(settings.TELEGRAM_SESSION_DIR and settings.TELEGRAM_SESSION_DIR.strip())
    if not has_strings and not has_dir:
        issues.append("Set TELEGRAM_SESSION_STRINGS and/or TELEGRAM_SESSION_DIR")

    return (len(issues) == 0, issues)
