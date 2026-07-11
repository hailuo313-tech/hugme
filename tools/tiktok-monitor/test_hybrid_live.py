from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

from live_db import (
    apply_probe_result,
    connect,
    init_db,
    list_live_sessions,
    managed_budget_stats,
    reserve_managed_budget,
)
from live_fetch import LiveStatus, fetch_live_status
from live_worker import (
    _apply_budgeted_consensus,
    _confirm_live_candidate,
    _consensus_status,
    managed_recheck_interval_minutes,
)
from managed_live import ManagedLiveStatus, fetch_managed_statuses
import web_app


class HybridLiveTests(unittest.TestCase):
    def test_dashboard_is_manual_only_and_button_still_triggers_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "accounts": [],
                        "live_monitor": {
                            "auto_probe_enabled": False,
                            "auto_sample_enabled": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(web_app, "CONFIG_PATH", config_path), patch.object(
                web_app, "DB_PATH", root / "live.sqlite"
            ):
                body = web_app.render_page(tab="live")

        self.assertIn('action="/tiktok-monitor/run-probe"', body)
        self.assertIn("立即检测全部账号", body)
        self.assertIn("只在点击按钮后执行，不自动检测", body)
        self.assertNotIn("自动每 2 分钟", body)
        self.assertNotIn("直播账号每 60 秒复核", body)

    def test_timer_installer_disables_automatic_detection(self) -> None:
        script = (
            Path(__file__).resolve().parent / "scripts" / "install_timers.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "systemctl disable --now tiktok-live-probe.timer tiktok-live-sample.timer",
            script,
        )
        self.assertNotIn("enable --now tiktok-live-probe.timer", script)
        self.assertNotIn("enable --now tiktok-live-sample.timer", script)

    def test_budget_hard_limit_and_category_pools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "live.sqlite"
            init_db(db_path)

            self.assertEqual(
                100,
                reserve_managed_budget(db_path, 150, category="candidate"),
            )
            self.assertEqual(
                600,
                reserve_managed_budget(db_path, 1000, category="active"),
            )
            self.assertEqual(
                0,
                reserve_managed_budget(db_path, 1, category="active"),
            )
            budget = managed_budget_stats(db_path)
            self.assertEqual(700, budget["used"])
            self.assertEqual(0, budget["remaining"])
            self.assertEqual(2.8, budget["estimated_cost_usd"])

    def test_concurrent_budget_reservations_cannot_exceed_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "live.sqlite"
            init_db(db_path)
            with ThreadPoolExecutor(max_workers=10) as executor:
                reserved = list(
                    executor.map(
                        lambda _: reserve_managed_budget(
                            db_path, 20, category="candidate"
                        ),
                        range(10),
                    )
                )

            self.assertEqual(100, sum(reserved))
            self.assertEqual(100, managed_budget_stats(db_path)["used"])

    def test_dynamic_recheck_interval_stays_within_active_pool(self) -> None:
        self.assertEqual(15, managed_recheck_interval_minutes(1))
        self.assertEqual(15, managed_recheck_interval_minutes(5))
        self.assertEqual(24, managed_recheck_interval_minutes(10))
        self.assertEqual(48, managed_recheck_interval_minutes(20))
        for active_count in range(1, 203):
            interval = managed_recheck_interval_minutes(active_count)
            daily_calls = active_count * ((1440 + interval - 1) // interval)
            self.assertLessEqual(daily_calls, 600)

    @patch("live_worker.fetch_managed_statuses")
    def test_candidate_requires_two_local_live_signals(
        self,
        managed_mock: Mock,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "live.sqlite"
            init_db(db_path)
            with connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO accounts
                    (username, display_name, profile_url, enabled, created_at, updated_at)
                    VALUES ('creator', 'creator', 'https://example.test', 1,
                            '2026-01-01', '2026-01-01')
                    """
                )
            managed_mock.return_value = {
                "creator": ManagedLiveStatus(
                    username="creator",
                    outcome="live",
                    source="managed:apify",
                )
            }
            local = {
                "creator": LiveStatus(
                    username="creator",
                    is_live=True,
                    room_id="123",
                    source="sigi+stream",
                )
            }

            with patch("live_worker.DB_PATH", db_path):
                first = _apply_budgeted_consensus(
                    local,
                    live_api={"enabled": True, "provider": "apify"},
                    managed_required=True,
                )["creator"]
                self.assertEqual("unknown", first.outcome)
                managed_mock.assert_not_called()
                apply_probe_result(
                    db_path,
                    username="creator",
                    is_live=False,
                    room_id="123",
                    title=None,
                    viewer_count=None,
                    source=first.source,
                    error=first.error,
                )
                second = _apply_budgeted_consensus(
                    local,
                    live_api={"enabled": True, "provider": "apify"},
                    managed_required=True,
                )["creator"]

            self.assertEqual("live", second.outcome)
            managed_mock.assert_called_once()
            self.assertEqual(1, managed_budget_stats(db_path)["used"])

    @patch("live_worker.fetch_managed_statuses")
    def test_exhausted_budget_never_confirms_live(self, managed_mock: Mock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "live.sqlite"
            init_db(db_path)
            with connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO accounts
                    (username, display_name, profile_url, enabled, local_live_streak,
                     created_at, updated_at)
                    VALUES ('creator', 'creator', 'https://example.test', 1, 1,
                            '2026-01-01', '2026-01-01')
                    """
                )
            reserve_managed_budget(db_path, 100, category="candidate")
            local = {
                "creator": LiveStatus(
                    username="creator",
                    is_live=True,
                    room_id="123",
                    source="sigi+stream",
                )
            }

            with patch("live_worker.DB_PATH", db_path):
                result = _apply_budgeted_consensus(
                    local,
                    live_api={"enabled": True, "provider": "apify"},
                    managed_required=True,
                )["creator"]

            self.assertEqual("unknown", result.outcome)
            self.assertIn("budget exhausted", str(result.error))
            managed_mock.assert_not_called()

    @patch("managed_live.requests.post")
    def test_apify_actor_response_is_parsed(self, post_mock: Mock) -> None:
        response = Mock()
        response.json.return_value = [
            {
                "handle": "creator",
                "is_live": True,
                "room_title": "Live now",
                "viewer_count": 123,
            }
        ]
        response.raise_for_status.return_value = None
        post_mock.return_value = response

        results = fetch_managed_statuses(
            ["creator"],
            {"enabled": True, "provider": "apify", "api_key": "test-token"},
        )

        self.assertEqual("live", results["creator"].outcome)
        self.assertEqual("Live now", results["creator"].title)
        self.assertEqual(123, results["creator"].viewer_count)
        self.assertEqual(["creator"], post_mock.call_args.kwargs["json"]["handles"])

    def test_offline_local_result_does_not_require_paid_confirmation(self) -> None:
        local = LiveStatus(username="creator", is_live=False, source="redirect")

        result = _confirm_live_candidate(
            local,
            {},
            managed_required=True,
        )

        self.assertEqual("offline", result.outcome)
        self.assertEqual("redirect", result.source)

    def test_unconfirmed_open_session_is_hidden_from_live_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "live.sqlite"
            init_db(db_path)
            with connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO accounts
                    (username, display_name, profile_url, enabled, last_probe_status,
                     created_at, updated_at)
                    VALUES ('creator', 'creator', 'https://example.test', 1, 'unknown',
                            '2026-01-01', '2026-01-01')
                    """
                )
                conn.execute(
                    """
                    INSERT INTO live_sessions (account_id, started_at, status)
                    VALUES (1, '2026-01-01', 'live')
                    """
                )

            self.assertEqual([], list_live_sessions(db_path, status="live"))
            self.assertEqual(
                1,
                len(list_live_sessions(db_path, status=None)),
            )

    def test_two_live_sources_confirm_live(self) -> None:
        local = LiveStatus(
            username="creator",
            is_live=True,
            room_id="123",
            source="sigi+stream",
        )
        managed = ManagedLiveStatus(
            username="creator",
            outcome="live",
            room_id="123",
            source="managed:test",
        )

        result = _consensus_status(local, managed, managed_required=True)

        self.assertTrue(result.is_live)
        self.assertIsNone(result.error)
        self.assertIn("managed:test", result.source)

    def test_conflicting_sources_are_pending(self) -> None:
        local = LiveStatus(
            username="creator",
            is_live=True,
            room_id="123",
            source="sigi+stream",
        )
        managed = ManagedLiveStatus(
            username="creator",
            outcome="offline",
            source="managed:test",
        )

        result = _consensus_status(local, managed, managed_required=True)

        self.assertFalse(result.is_live)
        self.assertEqual("unknown", result.outcome)
        self.assertIn("pending confirmation", str(result.error))

    @patch("live_fetch.validate_playback_stream", return_value=False)
    @patch("live_fetch.fetch_webcast_room", return_value=None)
    @patch("live_fetch._get_with_retry")
    def test_sigi_candidate_alone_is_not_live(
        self,
        get_mock: Mock,
        _webcast_mock: Mock,
        _stream_mock: Mock,
    ) -> None:
        sigi = {
            "LiveRoom": {
                "liveRoomUserInfo": {
                    "user": {"roomId": "123"},
                    "liveRoom": {
                        "roomId": "123",
                        "status": 4,
                        "streamData": {"pull_data": {"stream_data": "stale"}},
                    },
                }
            }
        }
        response = Mock()
        response.text = f"<script>SIGI_STATE={json.dumps(sigi)}</script>"
        response.url = "https://www.tiktok.com/@creator/live"
        get_mock.return_value = response

        result = fetch_live_status("creator")

        self.assertFalse(result.is_live)
        self.assertEqual("unknown", result.outcome)
        self.assertEqual("sigi_unverified", result.source)


if __name__ == "__main__":
    unittest.main()
