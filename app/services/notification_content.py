from __future__ import annotations

from typing import Any


def build_outbound_text(*, notification_type: str, payload: Any) -> str | None:
    """根据类型与 payload 生成出站文案；未知类型返回 None。"""
    p: dict[str, Any] = payload if isinstance(payload, dict) else {}
    n = (notification_type or "").strip().lower()

    if n == "silent_reactivation":
        tier = str(p.get("tier") or "D1").upper()
        lines = {
            "D1": (
                "Hi — we've been thinking of you. Whenever you're ready, "
                "we're here to chat. No rush."
            ),
            "D3": (
                "Hi — we'd love to pick up where you left off. "
                "If you feel like chatting, just send a message when it suits you."
            ),
            "D7": (
                "Hi — we'll step back for now. If you ever want to return, "
                "we're only a message away."
            ),
        }
        return lines.get(tier, lines["D1"])

    if n == "s5_care_checkin":
        return (
            "Hi — we're checking in. If things feel heavy, we're here to listen; "
            "message us whenever you feel able."
        )

    return None
