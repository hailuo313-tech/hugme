"""Lazy PyTgCalls instances bound to existing Telethon clients."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from loguru import logger

from services.telegram_account_manager import telegram_account_manager

_pytgcalls_by_account: dict[str, Any] = {}
_lock = asyncio.Lock()
_import_error: str | None = None


def _load_pytgcalls_class() -> type[Any]:
    global _import_error
    try:
        from pytgcalls import PyTgCalls
    except Exception as exc:  # pragma: no cover - optional dependency
        _import_error = str(exc)
        raise RuntimeError(f"pytgcalls not available: {exc}") from exc
    return PyTgCalls


async def get_pytgcalls(account_id: UUID) -> Any | None:
    """Return a started PyTgCalls wrapper for the connected Telethon account."""
    key = str(account_id)
    if key in _pytgcalls_by_account:
        return _pytgcalls_by_account[key]

    client = await telegram_account_manager.get_client(account_id)
    if client is None:
        return None

    async with _lock:
        if key in _pytgcalls_by_account:
            return _pytgcalls_by_account[key]
        PyTgCalls = _load_pytgcalls_class()
        wrapper = PyTgCalls(client)
        await wrapper.start()
        _pytgcalls_by_account[key] = wrapper
        logger.bind(account_id=key).info("call_broadcast.pytgcalls.started")
        return wrapper


async def release_pytgcalls(account_id: UUID) -> None:
    key = str(account_id)
    wrapper = _pytgcalls_by_account.pop(key, None)
    if wrapper is None:
        return
    for method_name in ("stop", "end"):
        method = getattr(wrapper, method_name, None)
        if callable(method):
            try:
                await method()
            except Exception as exc:
                logger.bind(account_id=key, error_type=type(exc).__name__).warning(
                    "call_broadcast.pytgcalls.release_failed"
                )
            break


def pytgcalls_import_error() -> str | None:
    return _import_error
