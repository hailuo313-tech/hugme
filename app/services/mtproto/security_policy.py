"""MTProto logging redaction and production guards (C-15)."""
from __future__ import annotations
import os
import re

_SENSITIVE = tuple(re.compile(p, re.I) for p in (
    r"TELEGRAM_SESSION_STRINGS\s*=\s*\S+",
    r"StringSession\([^)]+\)",
    r"\bauth_key\b",
    r"1BVts[A-Za-z0-9+/=_-]{20,}",
))
_REDACTED = "[REDACTED]"

def redact_sensitive(text: str) -> str:
    out = text
    for pat in _SENSITIVE:
        out = pat.sub(_REDACTED, out)
    return out

def assert_safe_log_message(message: str) -> None:
    if redact_sensitive(message) != message:
        raise ValueError("log message contains sensitive MTProto material")

def production_session_strings_forbidden() -> bool:
    env = (os.environ.get("ENV") or os.environ.get("APP_ENV") or "").strip().lower()
    if env not in ("production", "prod"):
        return False
    return bool((os.environ.get("TELEGRAM_SESSION_STRINGS") or "").strip())

def check_production_session_policy() -> list[str]:
    if production_session_strings_forbidden():
        return ["TELEGRAM_SESSION_STRINGS must be empty when ENV=production"]
    return []
