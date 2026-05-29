from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.attribution import (
    AttributionLinkCreate,
    admin_attribution_summary,
    create_attribution_link,
    delete_admin_attribution_clicked_user,
    redirect_tracking_link,
)
from services.link_attribution import (
    new_tracking_id,
    record_attribution_event,
    record_unique_click_event,
    tracking_url,
    wrap_text_links_with_tracking,
)


ROOT = Path(__file__).resolve().parents[1]


class FakeResult:
    def __init__(self, row=None, rows=None, rowcount=0):
        self.row = row
        self.rows = rows or []
        self.rowcount = rowcount

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class FakeSession:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.execute = AsyncMock(side_effect=self._execute)
        self.commit = AsyncMock(return_value=None)

    async def _execute(self, *args, **kwargs):
        return self.results.pop(0) if self.results else FakeResult()


def test_v9_migration_defines_attribution_storage() -> None:
    sql = (ROOT / "db" / "migration" / "V9__link_attribution.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS attribution_links" in sql
    assert "CREATE TABLE IF NOT EXISTS attribution_events" in sql
    assert "script_hit_id" in sql
    assert "country_code" in sql
    assert "ALTER TABLE orders" in sql
    assert "ADD COLUMN IF NOT EXISTS attribution_tracking_id" in sql


def test_v10_migration_adds_complete_analytics_dimensions() -> None:
    sql = (ROOT / "db" / "migration" / "V10__link_attribution_analytics.sql").read_text(encoding="utf-8")

    assert "sender_account_id" in sql
    assert "scene_step" in sql
    assert "script_category" in sql
    assert "is_t1_country" in sql
    assert "CREATE TABLE IF NOT EXISTS app_user_attribution_bindings" in sql


def test_tracking_id_and_url_are_url_safe() -> None:
    tracking_id = new_tracking_id()

    assert len(tracking_id) >= 12
    assert "/" not in tracking_id
    assert tracking_url("https://hugme2.com/", "trk_1") == "https://hugme2.com/r/trk_1"


async def test_record_attribution_event_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="unsupported attribution event_type"):
        await record_attribution_event(FakeSession(), tracking_id="trk", event_type="unknown")


async def test_create_attribution_link_persists_context_and_returns_redirect_url() -> None:
    db = FakeSession()
    request = SimpleNamespace(base_url="https://hugme2.com/")

    with patch("services.link_attribution.new_tracking_id", return_value="trk_test"):
        response = await create_attribution_link(
            AttributionLinkCreate(
                destination_url="https://app.example/download",
                user_id="user-1",
                script_hit_id="hit-1",
                campaign_id="spring",
                platform="telegram",
                country_code="us",
                age=29,
                user_level="a",
            ),
            request,
            {},
            db,
        )

    assert response.tracking_id == "trk_test"
    assert response.tracking_url == "https://hugme2.com/r/trk_test"
    params = db.execute.await_args.args[1]
    assert params["script_hit_id"] == "hit-1"
    assert params["country_code"] == "US"
    assert params["user_level"] == "A"
    db.commit.assert_awaited_once()


async def test_wrap_text_links_with_tracking_replaces_outbound_url() -> None:
    db = FakeSession()

    with patch("services.link_attribution.new_tracking_id", return_value="trk_reply"):
        wrapped = await wrap_text_links_with_tracking(
            db,
            text_value="Install here: https://app.example/download.",
            base_url="https://hugme2.com",
            user_id="user-1",
            conversation_id="conv-1",
            message_id="msg-1",
            script_hit_id="hit-1",
            campaign_id="spring",
            platform="telegram",
        )

    assert wrapped == "Install here: https://hugme2.com/r/trk_reply."
    params = db.execute.await_args_list[0].args[1]
    assert params["destination_url"] == "https://app.example/download"
    assert params["script_hit_id"] == "hit-1"
    assert params["message_id"] == "msg-1"
    event_params = db.execute.await_args_list[1].args[1]
    assert event_params["event_type"] == "link_exposed"
    assert event_params["tracking_id"] == "trk_reply"


async def test_redirect_tracking_link_records_click_then_redirects() -> None:
    db = FakeSession(
        results=[
            FakeResult(("https://app.example/download", "user-1", "US", 29, "A")),
            FakeResult(),
        ]
    )
    request = SimpleNamespace(
        headers={"user-agent": "pytest", "referer": "https://hugme2.com/chat"},
        client=SimpleNamespace(host="127.0.0.1"),
    )

    response = await redirect_tracking_link("trk_test", request, db)

    assert response.status_code == 302
    assert response.headers["location"] == "https://app.example/download"
    assert db.execute.await_count == 2
    event_params = db.execute.await_args_list[1].args[1]
    assert event_params["tracking_id"] == "trk_test"
    assert event_params["user_id"] == "user-1"
    event_sql = str(db.execute.await_args_list[1].args[0])
    assert "WHERE NOT EXISTS" in event_sql
    assert "event_type = 'click'" in event_sql
    db.commit.assert_awaited_once()


async def test_record_unique_click_event_dedupes_by_tracking_and_user() -> None:
    db = FakeSession()

    await record_unique_click_event(
        db,
        tracking_id="trk_test",
        user_id="00000000-0000-0000-0000-000000000001",
        country_code="us",
        user_level="a",
        ip_address="127.0.0.1",
        user_agent="pytest",
    )

    sql = str(db.execute.await_args.args[0])
    params = db.execute.await_args.args[1]
    assert "WHERE NOT EXISTS" in sql
    assert "CAST(:tracking_id AS varchar)" in sql
    assert "tracking_id IS NOT DISTINCT FROM CAST(:tracking_id AS varchar)" in sql
    assert "CAST(:user_id AS uuid) IS NOT NULL" in sql
    assert "user_id = CAST(:user_id AS uuid)" in sql
    assert "ip_address IS NOT DISTINCT FROM CAST(:ip_address AS INET)" in sql
    assert params["tracking_id"] == "trk_test"
    assert params["country_code"] == "US"
    assert params["user_level"] == "A"


async def test_admin_attribution_summary_returns_complete_dashboard_shape() -> None:
    overview = (
        3, 2, 3, 2, 2, 2, 4, 2, 1, 1, 1, 9900, 1, 2, 30.0, 120.0, 300.0
    )
    dimension = ("US", 3, 4, 2, 1, 1, 1, 9900, True)
    generic_dimension = ("A", 1, 2, 1, 1, 1, 1, 9900)
    script = (
        "hit-1",
        "tpl-1",
        "hit-1",
        "purchase_intent",
        "warm",
        "vip_cta",
        "tg-1",
        4,
        1,
        1,
        1,
        9900,
        "Open the app and we will continue.",
        "打开 App，我们继续聊。",
    )
    link = ("trk-1", "https://app.example/download", "hit-1", None, "tg-1", "telegram", 4, 2, None, 30.0)
    clicked_user = (
        "user-1",
        "tg_100",
        "Danica",
        "telegram_real_user",
        "US",
        "A",
        4,
        2,
        None,
        None,
        "trk-1",
        "https://app.example/download",
        "app_download_first_guide",
        "tg-1",
    )
    telegram_account = ("acc-1", "Mira TG", "+10000000000", "mira_tg", 5, 3, 12, None)
    db = FakeSession(
        results=[
            FakeResult(overview),
            FakeResult(rows=[dimension]),
            *[FakeResult(rows=[generic_dimension]) for _ in range(8)],
            *[FakeResult(rows=[script]) for _ in range(4)],
            FakeResult(rows=[link]),
            FakeResult(rows=[clicked_user]),
            FakeResult(rows=[telegram_account]),
        ]
    )

    out = await admin_attribution_summary(days=7, selected_date=date(2026, 5, 22), _={}, db=db)

    assert out["mode"] == "daily"
    assert out["date"] == "2026-05-22"
    assert out["overview"]["today_click_users"] == 2
    assert out["overview"]["click_rate"] == 1.0
    assert out["overview"]["avg_click_to_register_seconds"] == 120.0
    assert out["countries"][0]["is_t1_country"] is True
    assert out["funnel"][0]["step"] == "话术发送"
    assert out["top_click_scripts"][0]["intent"] == "purchase_intent"
    assert out["top_click_scripts"][0]["content"] == "Open the app and we will continue."
    assert out["top_click_scripts"][0]["operator_translation_zh"] == "打开 App，我们继续聊。"
    script_sql = "\n".join(call.args[0].text for call in db.execute.await_args_list)
    assert "st.id = l.script_template_id" in script_sql
    assert "st.id::text = l.script_hit_id" in script_sql
    assert out["top_payment_scripts"][0]["revenue_cents"] == 9900
    assert out["links"][0]["tracking_id"] == "trk-1"
    assert out["clicked_users"][0]["external_id"] == "tg_100"
    assert out["clicked_users"][0]["click_count"] == 4
    assert out["clicked_users"][0]["clicked_links"] == 2
    assert out["clicked_users"][0]["latest_tracking_id"] == "trk-1"
    clicked_users_sql = db.execute.await_args_list[-2].args[0].text
    assert "ORDER BY clicked.last_click_at DESC" in clicked_users_sql
    assert "LIMIT 500" in clicked_users_sql
    assert out["overview"]["tg_new_users"] == 3
    assert out["overview"]["tg_served_users"] == 5
    assert out["telegram_accounts"][0]["account_label"] == "Mira TG"
    assert out["telegram_accounts"][0]["new_users"] == 3
    assert out["telegram_accounts"][0]["served_users"] == 5
    assert db.execute.await_args_list[0].args[1]["start_at"] == date(2026, 5, 22)


async def test_delete_admin_attribution_clicked_user_removes_only_click_events() -> None:
    db = FakeSession(results=[FakeResult(rowcount=3)])

    out = await delete_admin_attribution_clicked_user(user_id="user-1", _={}, db=db)

    sql = db.execute.await_args.args[0].text
    params = db.execute.await_args.args[1]
    assert out == {"deleted_events": 3}
    assert "DELETE FROM attribution_events" in sql
    assert "e.event_type = 'click'" in sql
    assert "attribution_links" in sql
    assert params == {"user_id": "user-1"}
    db.commit.assert_awaited_once()
