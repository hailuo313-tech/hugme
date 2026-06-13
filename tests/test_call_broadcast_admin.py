"""Admin API helpers for video broadcast uploads."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from api.call_broadcast_admin import (
    ManualCallRequest,
    ManualCallTarget,
    _safe_video_suffix,
    _serialize_call_history_record,
    _serialize_call_history_user,
    _serialize_chat_user,
    _video_broadcast_dir,
    enqueue_manual_call_broadcast,
)
from services.call_broadcast.peers import resolve_account_and_access_hash


def test_safe_video_suffix_accepts_mp4() -> None:
    assert _safe_video_suffix("promo.mp4") == ".mp4"


def test_safe_video_suffix_rejects_unknown() -> None:
    with pytest.raises(HTTPException) as exc:
        _safe_video_suffix("notes.txt")
    assert exc.value.status_code == 422


def test_video_broadcast_dir_uses_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "api.call_broadcast_admin.settings.CALL_BROADCAST_VIDEO_ROOT",
        str(tmp_path / "videos"),
        raising=False,
    )
    path = _video_broadcast_dir()
    assert path.is_dir()
    assert path == tmp_path / "videos"


def test_serialize_call_history_record_formats_fields() -> None:
    from datetime import datetime, timezone

    row = SimpleNamespace(
        _mapping={
            "job_id": "job-1",
            "user_id": "9db0162d-88d8-40b7-9d92-dc789ee12e19",
            "external_id": "tg_8734778484",
            "chat_id": 8734778484,
            "call_at": datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc),
            "duration_seconds": 9,
            "trigger_source": "inbound_operator_review",
            "inbound_call_number": 2,
            "telegram_account_id": "b31fe0e5-c25d-4cb9-bf70-94078b94ffec",
            "telegram_account_label": "+8613800138000",
            "telegram_account_phone": "+8613800138000",
        }
    )
    item = _serialize_call_history_record(row)
    assert item["duration_seconds"] == 9
    assert item["call_at"].startswith("2026-05-24")
    assert item["inbound_call_number"] == 2
    assert item["telegram_account_label"] == "+8613800138000"


def test_serialize_call_history_user_formats_fields() -> None:
    from datetime import datetime, timezone

    row = SimpleNamespace(
        _mapping={
            "user_id": "9db0162d-88d8-40b7-9d92-dc789ee12e19",
            "external_id": "tg_8734778484",
            "chat_id": 8734778484,
            "call_count": 3,
            "last_call_at": datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc),
            "last_trigger_source": "inbound_call",
        }
    )
    item = _serialize_call_history_user(row)
    assert item["chat_id"] == 8734778484
    assert item["call_count"] == 3
    assert item["last_call_at"].startswith("2026-05-24")


def test_serialize_chat_user_adds_chat_id() -> None:
    row = SimpleNamespace(
        _mapping={
            "user_id": "u1",
            "external_id": "tg_12345",
            "nickname": "Alice",
        }
    )
    item = _serialize_chat_user(row)
    assert item["chat_id"] == 12345


@pytest.mark.asyncio
async def test_manual_calls_rejects_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(
        "api.call_broadcast_admin.settings",
        "CALL_BROADCAST_ENABLED",
        False,
        raising=False,
    )  # type: ignore[attr-defined]
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await enqueue_manual_call_broadcast(
            ManualCallRequest(
                video_asset_id="5c4b34b7-6b30-40d3-8aa8-65378aea4295",
                targets=[
                    ManualCallTarget(
                        user_id="9db0162d-88d8-40b7-9d92-dc789ee12e19",
                        conversation_id="08e2a358-b2c8-48bb-b8e3-28cc7d4f0618",
                    )
                ],
            ),
            request=MagicMock(state=SimpleNamespace(trace_id="t1")),
            db=db,
            operator={"sub": "op1"},
        )
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_resolve_account_and_access_hash_prefers_match(monkeypatch) -> None:
    from uuid import uuid4

    account_uuid = str(uuid4())
    fake_entity = type("E", (), {"id": 123, "access_hash": 999})()

    class _Client:
        async def get_entity(self, _peer):
            return fake_entity

    async def _get_client(_account_id):
        return _Client()

    fake_account = type("A", (), {"id": account_uuid, "is_active": True})()
    monkeypatch.setattr(
        "services.call_broadcast.peers.telegram_account_manager.get_active_accounts",
        AsyncMock(return_value=[fake_account]),
    )
    monkeypatch.setattr(
        "services.call_broadcast.peers.telegram_account_manager.get_client",
        _get_client,
    )

    account_id, access_hash = await resolve_account_and_access_hash(
        chat_id=123,
        preferred_account_id=account_uuid,
    )
    assert account_id == account_uuid
    assert access_hash == "999"
