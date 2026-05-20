"""D6-3 单元测试：``services.silent_reactivation`` 纯函数 + 资格判定。

不接 DB。Runner 的 SQL 与 admin 端点留给服务器手动 smoke。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.silent_reactivation import (
    evaluate_user,
    is_in_quiet_hours,
    next_send_time,
    select_tier,
)


# ── 测试用 user 行（与 init.sql 一致的字段） ───────────────────


def _user_row(
    *,
    user_id: str = "11111111-1111-1111-1111-111111111111",
    channel: str = "telegram",
    status: str = "active",
    notification_opt_in: bool = True,
    opt_out_marketing: bool = False,
    is_minor_suspected: bool = False,
    risk_level: str = "normal",
    timezone_name: str = "UTC",
) -> dict:
    return {
        "id": user_id,
        "channel": channel,
        "status": status,
        "notification_opt_in": notification_opt_in,
        "opt_out_marketing": opt_out_marketing,
        "is_minor_suspected": is_minor_suspected,
        "risk_level": risk_level,
        "timezone": timezone_name,
    }


# ── 静默时段 ──────────────────────────────────────────


def test_is_in_quiet_hours_utc_22_in_window():
    now = datetime(2026, 5, 12, 22, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(now, "UTC") is True


def test_is_in_quiet_hours_utc_07_in_window():
    now = datetime(2026, 5, 12, 7, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(now, "UTC") is True


def test_is_in_quiet_hours_utc_12_out_of_window():
    now = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(now, "UTC") is False


def test_is_in_quiet_hours_respects_timezone():
    # UTC 02:00 = Asia/Shanghai 10:00（非静默）
    now = datetime(2026, 5, 12, 2, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(now, "Asia/Shanghai") is False
    # UTC 14:00 = Asia/Shanghai 22:00（静默）
    now = datetime(2026, 5, 12, 14, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(now, "Asia/Shanghai") is True


def test_is_in_quiet_hours_invalid_tz_fallback_to_utc():
    now = datetime(2026, 5, 12, 22, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(now, "Not/A_Real_Zone") is True


def test_next_send_time_no_change_when_outside_window():
    now = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)
    out = next_send_time(now, "UTC")
    assert out.replace(tzinfo=timezone.utc) == now


def test_next_send_time_late_night_pushes_to_next_morning():
    # UTC 22:00（静默） → 次日本地 09:15 (UTC)
    now = datetime(2026, 5, 12, 22, 0, tzinfo=timezone.utc)
    out = next_send_time(now, "UTC")
    assert out.year == 2026 and out.month == 5 and out.day == 13
    assert out.hour == 9 and out.minute == 15


def test_next_send_time_early_morning_pushes_to_same_day_0915():
    # UTC 07:00（静默，<09:00） → 当日 09:15
    now = datetime(2026, 5, 12, 7, 0, tzinfo=timezone.utc)
    out = next_send_time(now, "UTC")
    assert out.year == 2026 and out.month == 5 and out.day == 12
    assert out.hour == 9 and out.minute == 15


# ── 分级 ──────────────────────────────────────────────


def test_select_tier_d1_window():
    assert select_tier(30, has_meaningful_memory=False) == "D1"


def test_select_tier_d3_requires_memory():
    assert select_tier(80, has_meaningful_memory=False) is None
    assert select_tier(80, has_meaningful_memory=True) == "D3"


def test_select_tier_d7_window():
    assert select_tier(8 * 24, has_meaningful_memory=False) == "D7"


def test_select_tier_outside_any_window():
    assert select_tier(10, has_meaningful_memory=True) is None  # 太早
    assert select_tier(48, has_meaningful_memory=True) is None  # 36~72h 间隙
    assert select_tier(150, has_meaningful_memory=True) is None  # 96h ~ 7d 间隙
    assert select_tier(24 * 30, has_meaningful_memory=True) is None  # 太晚


def test_select_tier_skips_already_sent_tier():
    assert select_tier(30, has_meaningful_memory=True, prior_tiers_sent={"D1"}) is None


# ── evaluate_user 各资格门 ────────────────────────────

NOW = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)


def _last_msg_hours_ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


def test_evaluate_happy_path_d1():
    user = _user_row()
    res = evaluate_user(
        user,
        now_utc=NOW,
        last_user_message_at=_last_msg_hours_ago(30),
        has_open_handoff=False,
        has_meaningful_memory=False,
        telegram_bot_token_present=True,
    )
    assert res.ok is True
    assert res.tier == "D1"
    assert res.payload is not None
    assert res.payload["strategy"] == "silent_reactivation"
    assert res.payload["template_hint"] == "gentle_check_in"
    assert res.dedupe_key and res.dedupe_key.startswith("silent_reactivation:D1:")
    # 12:00 UTC 不在静默 → scheduled_at ≈ NOW
    assert res.scheduled_at is not None


def test_evaluate_d3_uses_memory_signal_and_template_hint():
    user = _user_row()
    res = evaluate_user(
        user,
        now_utc=NOW,
        last_user_message_at=_last_msg_hours_ago(80),
        has_open_handoff=False,
        has_meaningful_memory=True,
        telegram_bot_token_present=True,
    )
    assert res.ok is True
    assert res.tier == "D3"
    assert res.payload["template_hint"] == "memory_reconnect"


def test_evaluate_skips_when_opt_out_marketing():
    user = _user_row(opt_out_marketing=True)
    res = evaluate_user(
        user,
        now_utc=NOW,
        last_user_message_at=_last_msg_hours_ago(30),
        has_open_handoff=False,
        has_meaningful_memory=False,
        telegram_bot_token_present=True,
    )
    assert res.ok is False
    assert res.skip_reason == "opt_out_marketing"


def test_evaluate_skips_when_minor_suspected():
    user = _user_row(is_minor_suspected=True)
    res = evaluate_user(
        user,
        now_utc=NOW,
        last_user_message_at=_last_msg_hours_ago(30),
        has_open_handoff=False,
        has_meaningful_memory=False,
        telegram_bot_token_present=True,
    )
    assert res.ok is False
    assert res.skip_reason == "is_minor_suspected"


def test_evaluate_skips_when_high_risk():
    user = _user_row(risk_level="high")
    res = evaluate_user(
        user,
        now_utc=NOW,
        last_user_message_at=_last_msg_hours_ago(30),
        has_open_handoff=False,
        has_meaningful_memory=False,
        telegram_bot_token_present=True,
    )
    assert res.ok is False
    assert res.skip_reason == "risk_level:high"


def test_evaluate_skips_when_open_handoff():
    user = _user_row()
    res = evaluate_user(
        user,
        now_utc=NOW,
        last_user_message_at=_last_msg_hours_ago(30),
        has_open_handoff=True,
        has_meaningful_memory=False,
        telegram_bot_token_present=True,
    )
    assert res.ok is False
    assert res.skip_reason == "open_handoff_task"


def test_evaluate_skips_when_no_user_message_history():
    user = _user_row()
    res = evaluate_user(
        user,
        now_utc=NOW,
        last_user_message_at=None,
        has_open_handoff=False,
        has_meaningful_memory=False,
        telegram_bot_token_present=True,
    )
    assert res.ok is False
    assert res.skip_reason == "no_user_message_history"


def test_evaluate_skips_when_bot_token_missing():
    user = _user_row()
    res = evaluate_user(
        user,
        now_utc=NOW,
        last_user_message_at=_last_msg_hours_ago(30),
        has_open_handoff=False,
        has_meaningful_memory=False,
        telegram_bot_token_present=False,
    )
    assert res.ok is False
    assert res.skip_reason == "bot_token_missing"


def test_evaluate_pushes_scheduled_at_when_quiet_hours():
    """凌晨 03:00 UTC：静默期；scheduled_at 应推到当日 09:15。"""
    user = _user_row()
    now = datetime(2026, 5, 12, 3, 0, tzinfo=timezone.utc)
    res = evaluate_user(
        user,
        now_utc=now,
        last_user_message_at=now - timedelta(hours=30),
        has_open_handoff=False,
        has_meaningful_memory=False,
        telegram_bot_token_present=True,
    )
    assert res.ok is True
    assert res.scheduled_at is not None
    assert res.scheduled_at.hour == 9 and res.scheduled_at.minute == 15


def test_dedupe_key_includes_local_date_for_non_utc_user():
    """同一 UTC 时刻、不同时区，本地日期不同 → dedupe_key 不同。"""
    now = datetime(2026, 5, 12, 23, 30, tzinfo=timezone.utc)  # 北京 5/13 07:30
    user_bj = _user_row(timezone_name="Asia/Shanghai")
    res = evaluate_user(
        user_bj,
        now_utc=now,
        last_user_message_at=now - timedelta(hours=30),
        has_open_handoff=False,
        has_meaningful_memory=False,
        telegram_bot_token_present=True,
    )
    # 在该时区是早 07:30，是静默期（<09:00）→ scheduled_at 推到本地 09:15
    assert res.ok is True
    assert res.dedupe_key is not None
    assert ":2026-05-13" in res.dedupe_key
