"""Fixed auto-reply worker: fair dispatch settings and recovery."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import fixed_auto_reply_service as svc


def test_cfg_reads_settings():
    assert svc._cfg("FIXED_AUTO_REPLY_PER_ACCOUNT_BATCH", 10) >= 1


@pytest.mark.asyncio
async def test_recover_stuck_jobs_resets_sending_to_pending():
    svc._schema_ready = True
    db = MagicMock()
    failed_result = MagicMock(rowcount=0)
    recovered_result = MagicMock(rowcount=3)
    db.execute = AsyncMock(side_effect=[failed_result, recovered_result])

    result = await svc._recover_stuck_jobs(db)

    assert result == {"recovered_to_pending": 3, "marked_failed": 0}
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_send_tick_skips_when_already_running():
    svc._send_tick_running = True
    try:
        result = await svc.run_fixed_auto_reply_send_tick()
        assert result["skipped"] == 1
    finally:
        svc._send_tick_running = False


@pytest.mark.asyncio
async def test_claim_due_jobs_fair_uses_per_account_limit():
    svc._schema_ready = True
    db = MagicMock()
    row = MagicMock()
    row._mapping = {
        "id": "job-1",
        "rule_id": "rule-1",
        "user_id": "user-1",
        "conversation_id": "conv-1",
        "external_user_id": "tg_1",
        "account_id": "acct-1",
        "chat_id": 123,
        "telegram_access_hash": 456,
    }
    claim = MagicMock()
    claim.fetchall.return_value = [row]
    db.execute = AsyncMock(return_value=claim)
    db.commit = AsyncMock()

    jobs = await svc._claim_due_jobs_fair(
        db,
        trace_id="trace-1",
        per_account_limit=10,
        total_limit=200,
    )

    assert len(jobs) == 1
    sql = db.execute.await_args.args[0].text
    assert "PARTITION BY j.account_id" in sql
    assert "rn <= :per_account_limit" in sql
