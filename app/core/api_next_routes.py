"""Stage 5 path split: ordinary traffic can move to api-next.

Telegram control and video stay on the process that owns Telegram sessions.
Nginx should route by these prefixes; the FastAPI app itself stays one image.
"""

from __future__ import annotations

TELEGRAM_CONTROL_PREFIXES = (
    "/api/v1/telegram/",
    "/api/v1/mtproto",
    "/api/v1/telegram-user-migration/",
)

VIDEO_PREFIXES = (
    "/api/v1/call-broadcast/",
    "/api/v1/video-reinvite/",
)

ORDINARY_EXAMPLES = (
    "/api/v1/users",
    "/api/v1/admin/users",
    "/health",
    "/health/detail",
)


def classify_path(path: str) -> str:
    raw = str(path or "")
    if not raw.startswith("/"):
        raw = "/" + raw
    for prefix in VIDEO_PREFIXES:
        if raw.startswith(prefix):
            return "video"
    for prefix in TELEGRAM_CONTROL_PREFIXES:
        if raw.startswith(prefix):
            return "telegram_control"
    return "ordinary"


def api_next_may_serve(path: str) -> bool:
    return classify_path(path) == "ordinary"


def legacy_api_must_serve(path: str) -> bool:
    return classify_path(path) in {"telegram_control", "video"}
