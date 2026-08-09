from datetime import datetime, timezone

import pytest

from services.outbound_account_gate import check_outbound_account


class _Result:
    def __init__(self, row): self._row = row
    def mappings(self): return self
    def first(self): return self._row


class _DB:
    def __init__(self, row): self.row = row
    async def execute(self, *_args, **_kwargs): return _Result(self.row)


@pytest.mark.asyncio
async def test_outbound_gate_allows_healthy_connected_account():
    allowed, reason, _ = await check_outbound_account(_DB({
        "status": "connected", "is_active": True, "health_status": "active",
        "health_check_status": "healthy", "resume_at": None,
    }), "00000000-0000-0000-0000-000000000001")
    assert allowed is True
    assert reason == "active"


@pytest.mark.asyncio
async def test_outbound_gate_blocks_paused_account():
    allowed, reason, _ = await check_outbound_account(_DB({
        "status": "connected", "is_active": True, "health_status": "paused",
        "health_check_status": "restricted", "resume_at": datetime.now(timezone.utc),
    }), "00000000-0000-0000-0000-000000000001")
    assert allowed is False
    assert reason == "account_paused"
