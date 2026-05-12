"""
D6-3 Silent Reactivation —— 资格判定 + 分级 + 调度时间 + dedupe key（纯函数）。

与 ``D6-3_SILENT_REACTIVATION_STRATEGY.md`` 对齐：
- 资格门：active / opt_in / not_opt_out_marketing / not_minor / risk_level / open_handoff。
- 分级 D1/D3/D7：基于「距上一次 user 消息的时长」与已有 attempt。
- 静默时段：本地 21:30–09:00；命中则推到下一个本地 09:15。
- Dedupe key：``silent_reactivation:<tier>:<user_id>:<本地日期>``。
- 不做 DB IO；不发送；只产出结构化结果。Runner 与 API 自己负责落库。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


# ── 静默时段 / 时区 ───────────────────────────────────

QUIET_START = time(21, 30)   # 本地 21:30 起静默
QUIET_END = time(9, 0)       # 本地 09:00 解除
QUIET_RESUME = time(9, 15)   # 命中静默时改约到当日 09:15


def _resolve_tz(tz_name: str | None) -> ZoneInfo:
    if not tz_name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")
    except Exception:
        return ZoneInfo("UTC")


def is_in_quiet_hours(now_utc: datetime, tz_name: str | None) -> bool:
    """now_utc 在该用户所在时区是否处于 21:30–09:00 静默窗口内。"""
    tz = _resolve_tz(tz_name)
    local = _to_local(now_utc, tz)
    t = local.time()
    # 跨日窗口：21:30 → 次日 09:00
    return t >= QUIET_START or t < QUIET_END


def next_send_time(now_utc: datetime, tz_name: str | None) -> datetime:
    """返回 ``now_utc`` 如果当前是静默时段则推到下一个本地 ``09:15``，否则返回原值。

    返回值统一为 **naive UTC**（与 notification_tasks 表 / API 现有写法一致）。
    """
    tz = _resolve_tz(tz_name)
    local = _to_local(now_utc, tz)

    if not is_in_quiet_hours(now_utc, tz_name):
        return _to_naive_utc(now_utc)

    # 命中静默：算下一个本地 09:15
    if local.time() >= QUIET_START:
        # 今晚 21:30+ → 明早 09:15
        target_local = (local + timedelta(days=1)).replace(
            hour=QUIET_RESUME.hour, minute=QUIET_RESUME.minute, second=0, microsecond=0
        )
    else:
        # 凌晨 00:00 ~ 09:00 → 今天 09:15
        target_local = local.replace(
            hour=QUIET_RESUME.hour, minute=QUIET_RESUME.minute, second=0, microsecond=0
        )
    return _to_naive_utc(target_local.astimezone(timezone.utc))


# ── 分级 ──────────────────────────────────────────────

# 单位：小时
D1_MIN_HOURS, D1_MAX_HOURS = 24, 36
D3_MIN_HOURS, D3_MAX_HOURS = 72, 96
D7_MIN_HOURS, D7_MAX_HOURS = 24 * 7, 24 * 9


def select_tier(
    hours_since_last_message: float,
    has_meaningful_memory: bool,
    prior_tiers_sent: set[str] | None = None,
) -> str | None:
    """根据距上一次 user 消息的时长选择 tier；不符合任何窗口返回 ``None``。

    Args:
        hours_since_last_message: 自最近一次 user 消息以来的小时数。
        has_meaningful_memory: 是否存在可引用的非敏感记忆（D3 需要）。
        prior_tiers_sent: 这条会话/用户已经发过的 silent_reactivation tier 集合
            （用于避免重复发同档；spec 还要求 D3 在 D1 失败后再发，本期最小实现
             仅做"同档不重复"判定，跨档冷却由频次门 + dedupe 兜底）。
    """
    prior_tiers_sent = prior_tiers_sent or set()

    if D1_MIN_HOURS <= hours_since_last_message <= D1_MAX_HOURS and "D1" not in prior_tiers_sent:
        return "D1"
    if (
        D3_MIN_HOURS <= hours_since_last_message <= D3_MAX_HOURS
        and has_meaningful_memory
        and "D3" not in prior_tiers_sent
    ):
        return "D3"
    if D7_MIN_HOURS <= hours_since_last_message <= D7_MAX_HOURS and "D7" not in prior_tiers_sent:
        return "D7"
    return None


# ── 资格评估 ──────────────────────────────────────────

@dataclass(frozen=True)
class EligibilityResult:
    """单个候选用户的评估结果。"""

    ok: bool
    skip_reason: str | None = None
    tier: str | None = None
    scheduled_at: datetime | None = None
    dedupe_key: str | None = None
    payload: dict[str, Any] | None = None


# 这些字段必须在 user_row 上提供（与 init.sql 一致）
_REQUIRED_USER_FIELDS = (
    "id",
    "channel",
    "status",
    "notification_opt_in",
    "opt_out_marketing",
    "is_minor_suspected",
    "risk_level",
    "timezone",
)


def evaluate_user(
    user_row: Mapping[str, Any],
    *,
    now_utc: datetime,
    last_user_message_at: datetime | None,
    has_open_handoff: bool,
    has_meaningful_memory: bool,
    telegram_bot_token_present: bool,
    prior_tiers_sent: set[str] | None = None,
) -> EligibilityResult:
    """对单个候选用户做完整资格判定。

    与 spec §"Non-Negotiable Gates" 一一对应。Runner 把 DB 行抽出来后
    调用本函数；本函数纯计算。
    """
    # 容错：缺字段视为不满足
    for f in _REQUIRED_USER_FIELDS:
        if f not in user_row:
            return EligibilityResult(ok=False, skip_reason=f"missing_field:{f}")

    if user_row["channel"] != "telegram":
        return EligibilityResult(ok=False, skip_reason="channel_not_telegram")
    if not telegram_bot_token_present:
        return EligibilityResult(ok=False, skip_reason="bot_token_missing")
    if user_row["status"] != "active":
        return EligibilityResult(ok=False, skip_reason="user_not_active")
    if not user_row["notification_opt_in"]:
        return EligibilityResult(ok=False, skip_reason="notification_opt_in_false")
    if user_row["opt_out_marketing"]:
        return EligibilityResult(ok=False, skip_reason="opt_out_marketing")
    if user_row["is_minor_suspected"]:
        return EligibilityResult(ok=False, skip_reason="is_minor_suspected")
    if user_row["risk_level"] in ("high", "critical"):
        return EligibilityResult(ok=False, skip_reason=f"risk_level:{user_row['risk_level']}")
    if has_open_handoff:
        return EligibilityResult(ok=False, skip_reason="open_handoff_task")

    if last_user_message_at is None:
        return EligibilityResult(ok=False, skip_reason="no_user_message_history")

    hours = _hours_between(last_user_message_at, now_utc)
    tier = select_tier(hours, has_meaningful_memory, prior_tiers_sent)
    if tier is None:
        return EligibilityResult(ok=False, skip_reason="no_tier_match")

    scheduled_at = next_send_time(now_utc, user_row.get("timezone"))
    user_id = str(user_row["id"])
    tz_name = user_row.get("timezone") or "UTC"
    local_date = _to_local(now_utc, _resolve_tz(tz_name)).date().isoformat()
    dedupe_key = f"silent_reactivation:{tier}:{user_id}:{local_date}"

    payload: dict[str, Any] = {
        "strategy": "silent_reactivation",
        "tier": tier,
        "reason": _reason_for_tier(tier),
        "quiet_hours_checked": True,
        "timezone": tz_name,
        "template_hint": _template_hint_for_tier(tier),
        "safety": {
            "risk_level": user_row["risk_level"],
            "notification_opt_in": bool(user_row["notification_opt_in"]),
            "opt_out_marketing": bool(user_row["opt_out_marketing"]),
        },
        "dedupe_key": dedupe_key,
    }
    return EligibilityResult(
        ok=True,
        tier=tier,
        scheduled_at=scheduled_at,
        dedupe_key=dedupe_key,
        payload=payload,
    )


# ── 内部 helper ──────────────────────────────────────

def _to_local(dt: datetime, tz: ZoneInfo) -> datetime:
    """把 dt（可能 naive UTC 或 aware）映射到指定时区，返回 aware。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def _to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _hours_between(earlier: datetime, later: datetime) -> float:
    """两个 datetime 之间的小时差（容忍 naive / aware 混用，naive 视为 UTC）。"""
    if earlier.tzinfo is None:
        earlier = earlier.replace(tzinfo=timezone.utc)
    if later.tzinfo is None:
        later = later.replace(tzinfo=timezone.utc)
    return max(0.0, (later - earlier).total_seconds() / 3600.0)


def _reason_for_tier(tier: str) -> str:
    return {
        "D1": "inactive_24h",
        "D3": "inactive_72h",
        "D7": "inactive_7d",
    }.get(tier, "inactive")


def _template_hint_for_tier(tier: str) -> str:
    return {
        "D1": "gentle_check_in",
        "D3": "memory_reconnect",
        "D7": "final_ping",
    }.get(tier, "gentle_check_in")
