"""单元测试：app/api/telegram.py — bot 命令处理 (_handle_command)

覆盖：
- /help    → 返回 HELP_TEXT
- /privacy → 返回 PRIVACY_TEXT
- /reset   → 返回 RESET_PROMPT_TEXT
- /start   → 返回 None（交给 onboarding）
- 未知命令 → 返回 None
- 带 @bot_username 后缀 → 正确处理
- 带额外参数 → 正确处理
"""
from __future__ import annotations

import pytest


@pytest.fixture
def tg_module():
    """导入 telegram 模块（延迟导入，避免加载时依赖问题）。"""
    import importlib
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
    """'/start' 应返回 None，交给 onboarding 流程处理。"""
    result = await tg_module._handle_command("/start")
    assert result is None


@pytest.mark.asyncio
async def test_unknown_command_returns_none(tg_module):
    result = await tg_module._handle_command("/foobar")
    assert result is None


@pytest.mark.asyncio
async def test_help_with_bot_username_suffix(tg_module):
    """'/help@eris_bot' 应当正确匹配 /help。"""
    result = await tg_module._handle_command("/help@eris_bot")
    assert result is not None
    assert "命令列表" in result


@pytest.mark.asyncio
async def test_privacy_with_extra_args(tg_module):
    """'/privacy some extra text' 应当正确匹配 /privacy。"""
    result = await tg_module._handle_command("/privacy some extra text")
    assert result is not None
    assert "隐私说明" in result


@pytest.mark.asyncio
async def test_reset_with_bot_suffix_and_args(tg_module):
    """'/reset@my_bot please' 应当正确匹配 /reset。"""
    result = await tg_module._handle_command("/reset@my_bot please")
    assert result is not None
    assert "CONFIRM-DELETE" in result
