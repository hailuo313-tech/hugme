from __future__ import annotations

from uuid import uuid4

import pytest
from prometheus_client import REGISTRY, generate_latest

from services.account_monitor import account_monitor
from services.alert_scheduler import AlertRule, AlertScheduler


def test_p1_20_metrics_scrape_contains_account_monitor_series():
    account_id = str(uuid4())
    account_monitor.account_online.labels(account_id=account_id, phone="redacted").set(1)
    account_monitor.account_banned.labels(account_id=account_id, phone="redacted").set(0)
    account_monitor.message_send_success_rate.labels(
        account_id=account_id,
        phone="redacted",
    ).set(0.97)

    scrape = generate_latest(REGISTRY).decode("utf-8")

    assert "eris_telegram_account_online" in scrape
    assert f'account_id="{account_id}"' in scrape
    assert "eris_telegram_account_banned" in scrape
    assert "eris_telegram_message_send_success_rate" in scrape


@pytest.mark.asyncio
async def test_p1_20_alert_scheduler_triggers_and_resolves_account_alert():
    scheduler = AlertScheduler(check_interval=60)
    scheduler.alert_rules = [
        AlertRule(
            name="account_offline",
            condition="is_connected == False and is_banned == False",
            severity="warning",
            description="Account is offline",
            cooldown_minutes=0,
        )
    ]

    stat = {
        "account_id": "acc-1",
        "phone": "redacted",
        "is_connected": False,
        "is_banned": False,
        "error_rate": 0.0,
        "send_success_rate": 1.0,
    }

    await scheduler._check_account_alerts(stat)
    assert "acc-1_account_offline" in scheduler.active_alerts

    stat["is_connected"] = True
    await scheduler._check_resolved_alerts([stat])
    assert scheduler.active_alerts == {}
    assert scheduler.alert_history[0].resolved is True
