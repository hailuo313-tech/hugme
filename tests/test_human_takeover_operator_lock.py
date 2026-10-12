from datetime import datetime, timedelta, timezone

from services.human_takeover_gate import _idle_deadline_passed, evaluate_human_takeover_gate
import inspect


def test_idle_never_releases_after_operator_reply() -> None:
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    assert _idle_deadline_passed(
        now=now,
        takeover_at=now - timedelta(hours=3),
        last_user_at=now - timedelta(minutes=1),
        last_operator_at=now - timedelta(hours=1),
        idle_seconds=60,
    ) is False


def test_idle_can_release_when_operator_never_replied() -> None:
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    assert _idle_deadline_passed(
        now=now,
        takeover_at=now - timedelta(hours=2),
        last_user_at=now - timedelta(hours=1),
        last_operator_at=None,
        idle_seconds=60,
    ) is True


def test_evaluate_blocks_when_operator_has_replied() -> None:
    source = inspect.getsource(evaluate_human_takeover_gate)
    assert "human_operator_replied" in source
    assert "last_operator_at is not None" in source