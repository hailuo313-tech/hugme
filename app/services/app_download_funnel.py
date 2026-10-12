"""App-download funnel mode helpers (third-party click-only vs full attribution)."""

from __future__ import annotations

from core.config import settings

CLICK_POST_FOLLOWUP_TRIGGERS: frozenset[str] = frozenset(
    {
        "clicked_post_followup_2m",
        "clicked_not_downloaded_10m",
    }
)


def app_download_click_only() -> bool:
    """True when measurable success is link click (third-party promotion)."""
    return (settings.APP_DOWNLOAD_FUNNEL_MODE or "click_only").strip().lower() == "click_only"


def click_promotion_complete(
    *,
    clicked: bool,
    clicked_followup_sent: bool = False,
    hours_since_click: float | None = None,
) -> bool:
    """In click_only mode, stop auto link pushes after follow-up or 24h cooldown."""
    if not app_download_click_only() or not clicked:
        return False
    if clicked_followup_sent:
        return True
    if hours_since_click is not None and hours_since_click >= 24:
        return True
    return False
