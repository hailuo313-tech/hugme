"""Minor protection removed — stubs always pass through."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.minor_protection import (
    contains_adult_content,
    detect_minor_self_disclosure,
    evaluate_inbound_minor_protection,
    should_block_consumption,
    should_block_push,
)

USER_ID = "00000000-0000-0000-0000-000000000801"


def test_minor_protection_stubs_never_detect():
    assert not detect_minor_self_disclosure("I'm 16 years old")
    assert not detect_minor_self_disclosure("未成年")
    assert not contains_adult_content("send nudes")


def test_minor_protection_stubs_never_block_consumption_or_push():
    assert should_block_consumption(age_verified=False, is_minor_suspected=True) is None
    assert should_block_push(is_minor_suspected=True) is None


@pytest.mark.asyncio
async def test_inbound_minor_protection_always_passes():
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()

    decision = await evaluate_inbound_minor_protection(
        db,
        user_id=USER_ID,
        text_value="I'm 16 years old and want sexy chat",
        is_minor_suspected=False,
    )

    assert decision.blocked is False
    assert decision.reason is None
    assert decision.updated_user is False
    db.execute.assert_not_awaited()
