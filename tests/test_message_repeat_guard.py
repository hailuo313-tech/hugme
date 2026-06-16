from types import SimpleNamespace

import pytest

import services.message_repeat_guard as guard
from services.message_repeat_guard import (
    canonical_outbound_content,
    should_skip_duplicate_outbound,
    user_recently_received_same_content,
)


def test_canonical_outbound_content_strips_tracking_links() -> None:
    a = "Hello https://hugme2.com/r/abc123 (Use code: c5a8we)"
    b = "Hello https://hugme2.com/r/xyz789 (code: c5a8we)"
    assert canonical_outbound_content(a) == canonical_outbound_content(b)


def test_canonical_outbound_content_preserves_distinct_text() -> None:
    assert canonical_outbound_content("Still here?") != canonical_outbound_content("Hey there")


@pytest.mark.asyncio
async def test_user_recently_received_same_content_detects_repeat(monkeypatch) -> None:
    class FakeDb:
        async def execute(self, _sql, params=None):
            return SimpleNamespace(
                fetchall=lambda: [
                    SimpleNamespace(
                        _mapping={
                            "content": "Perfect — tap call on my profile now and I'll pick up right away."
                        }
                    )
                ]
            )

    monkeypatch.setattr(guard.settings, "OUTBOUND_MESSAGE_REPEAT_COOLDOWN_HOURS", 2)

    assert await user_recently_received_same_content(
        FakeDb(),
        user_id="11111111-1111-1111-1111-111111111111",
        content="Perfect — tap call on my profile now and I'll pick up right away.",
    )


@pytest.mark.asyncio
async def test_user_recently_received_same_content_allows_new_text(monkeypatch) -> None:
    class FakeDb:
        async def execute(self, _sql, params=None):
            return SimpleNamespace(
                fetchall=lambda: [
                    SimpleNamespace(_mapping={"content": "Still here? Tap call on my profile."})
                ]
            )

    monkeypatch.setattr(guard.settings, "OUTBOUND_MESSAGE_REPEAT_COOLDOWN_HOURS", 2)

    assert not await user_recently_received_same_content(
        FakeDb(),
        user_id="11111111-1111-1111-1111-111111111111",
        content="Hey, I'm online whenever you're ready.",
    )


@pytest.mark.asyncio
async def test_should_skip_duplicate_outbound_when_disabled(monkeypatch) -> None:
    class FakeDb:
        async def execute(self, _sql, params=None):
            raise AssertionError("db should not be queried when guard disabled")

    monkeypatch.setattr(guard.settings, "OUTBOUND_MESSAGE_REPEAT_COOLDOWN_HOURS", 0)

    assert not await should_skip_duplicate_outbound(
        FakeDb(),
        user_id="11111111-1111-1111-1111-111111111111",
        content="duplicate text",
    )
