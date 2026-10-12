from __future__ import annotations

from datetime import date as date_type, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

REPORT_TIMEZONE = "Asia/Shanghai"
_BJ = ZoneInfo(REPORT_TIMEZONE)


def beijing_now() -> datetime:
    return datetime.now(_BJ)


def beijing_today() -> date_type:
    return beijing_now().date()


def beijing_day_bounds(day: date_type) -> tuple[datetime, datetime]:
    """Return UTC-naive timestamps for [day 00:00 BJ, next day 00:00 BJ)."""
    start_local = datetime(day.year, day.month, day.day, tzinfo=_BJ)
    end_local = start_local + timedelta(days=1)
    return (
        start_local.astimezone(timezone.utc).replace(tzinfo=None),
        end_local.astimezone(timezone.utc).replace(tzinfo=None),
    )


def beijing_report_window(
    *,
    days: int,
    selected_date: date_type | None = None,
) -> dict[str, object]:
    """Build inclusive Beijing calendar windows for attribution dashboards."""
    today = beijing_today()
    today_start, today_end = beijing_day_bounds(today)

    if selected_date:
        start_at, end_at = beijing_day_bounds(selected_date)
        mode = "daily"
        report_date = selected_date
        range_start_date = selected_date
        range_end_date = selected_date
    elif days == 7:
        week_start = today - timedelta(days=today.weekday())
        start_at, _ = beijing_day_bounds(week_start)
        _, end_at = beijing_day_bounds(today)
        mode = "range"
        report_date = None
        range_start_date = week_start
        range_end_date = today
    else:
        range_start = today - timedelta(days=days - 1)
        start_at, _ = beijing_day_bounds(range_start)
        _, end_at = beijing_day_bounds(today)
        mode = "range"
        report_date = None
        range_start_date = range_start
        range_end_date = today

    return {
        "days": days,
        "date": report_date,
        "mode": mode,
        "timezone": REPORT_TIMEZONE,
        "start_at": start_at,
        "end_at": end_at,
        "today_start": today_start,
        "today_end": today_end,
        "range_start_date": range_start_date.isoformat(),
        "range_end_date": range_end_date.isoformat(),
    }
