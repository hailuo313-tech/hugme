"""Telegram bot command handling."""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def tg_module():
    import api.telegram as mod

    importlib.reload(mod)
    return mod


@pytest.mark.asyncio
async def test_help_returns_help_text(tg_module):
    result = await tg_module._handle_command("/help")
    assert result is not None
    assert "命令列表" in result
    assert "/start" in result
    assert "/help" in result
    assert "/reset" in result
    assert "/privacy" in result


@pytest.mark.asyncio
async def test_privacy_returns_privacy_text(tg_module):
    result = await tg_module._handle_command("/privacy")
    assert result is not None
    assert "隐私说明" in result
    assert "hello@hugme2.com" in result


@pytest.mark.asyncio
async def test_reset_returns_confirm_prompt(tg_module):
    result = await tg_module._handle_command("/reset")
    assert result is not None
    assert "CONFIRM-DELETE" in result
    assert "确认删除" in result


@pytest.mark.asyncio
async def test_start_returns_none(tg_module):
    result = await tg_module._handle_command("/start")
    assert result is None


@pytest.mark.asyncio
async def test_unknown_command_returns_none(tg_module):
    result = await tg_module._handle_command("/foobar")
    assert result is None


@pytest.mark.asyncio
async def test_help_with_bot_username_suffix(tg_module):
    result = await tg_module._handle_command("/help@eris_bot")
    assert result is not None
    assert "命令列表" in result


@pytest.mark.asyncio
async def test_privacy_with_extra_args(tg_module):
    result = await tg_module._handle_command("/privacy some extra text")
    assert result is not None
    assert "隐私说明" in result


@pytest.mark.asyncio
async def test_reset_with_bot_suffix_and_args(tg_module):
    result = await tg_module._handle_command("/reset@my_bot please")
    assert result is not None
    assert "CONFIRM-DELETE" in result
