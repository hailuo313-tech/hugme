"""Lazy PyTgCalls instances bound to existing Telethon clients."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Callable
from uuid import UUID

from loguru import logger

from services.telegram_account_manager import telegram_account_manager

_pytgcalls_by_account: dict[str, Any] = {}
_account_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
_import_error: str | None = None
_on_create: Callable[[Any, str], None] | None = None
_wrapper_handlers: dict[str, tuple[Any, list[Any]]] = {}


def set_pytgcalls_on_create(hook: Callable[[Any, str], None] | None) -> None:
    """Run before PyTgCalls.start() so inbound handlers attach first."""
    global _on_create
    _on_create = hook


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
        logger.bind(account_id=key).warning(
            "call_broadcast.pytgcalls.client_missing_reconnect"
        )
        try:
            success = await telegram_account_manager.connect_account(account_id)
        except Exception as exc:
            logger.bind(account_id=key, error_type=type(exc).__name__).warning(
                "call_broadcast.pytgcalls.reconnect_failed"
            )
            success = False
        if success:
            client = await telegram_account_manager.get_client(account_id)
    if client is None:
        return None

    async with _account_locks[key]:
        if key in _pytgcalls_by_account:
            return _pytgcalls_by_account[key]
        PyTgCalls = _load_pytgcalls_class()
        existing_handlers = {id(handler) for handler, _ in client.list_event_handlers()}
        wrapper = PyTgCalls(client)
        handlers = [
            handler for handler, _ in client.list_event_handlers()
            if id(handler) not in existing_handlers
        ]
        _wrapper_handlers[key] = (client, handlers)
        if _on_create is not None:
            try:
                _on_create(wrapper, key)
            except Exception as exc:
                logger.bind(account_id=key, error_type=type(exc).__name__).warning(
                    "call_broadcast.pytgcalls.on_create_failed"
                )
        try:
            await wrapper.start()
        except BaseException:
            for handler in handlers:
                client.remove_event_handler(handler)
            _wrapper_handlers.pop(key, None)
            raise
        _pytgcalls_by_account[key] = wrapper
        logger.bind(account_id=key).info("call_broadcast.pytgcalls.started")
        return wrapper


async def reset_pytgcalls(account_id: UUID) -> Any | None:
    """Drop a cached PyTgCalls wrapper and start a fresh one."""
    await release_pytgcalls(account_id)
    return await get_pytgcalls(account_id)


async def release_pytgcalls(account_id: UUID) -> None:
    key = str(account_id)
    async with _account_locks[key]:
        wrapper = _pytgcalls_by_account.pop(key, None)
        registration = _wrapper_handlers.pop(key, None)
        if registration is not None:
            client, handlers = registration
            for handler in handlers:
                client.remove_event_handler(handler)
        if wrapper is None:
            return
        # PyTgCalls has no global stop() in the deployed version. Detach its
        # adapter without disconnecting the shared Telegram messaging client.
        adapter = getattr(wrapper, "_app", None)
        callbacks = getattr(adapter, "_callbacks", None)
        if isinstance(callbacks, list):
            callbacks.clear()
        try:
            binding = getattr(wrapper, "_binding", None)
            if binding is not None:
                calls = await asyncio.wait_for(binding.calls(), timeout=5)
                for chat_id in calls:
                    await asyncio.wait_for(binding.stop(chat_id), timeout=5)
        except Exception as exc:
            logger.bind(account_id=key, error_type=type(exc).__name__).warning(
                "call_broadcast.pytgcalls.release_failed"
            )


def pytgcalls_import_error() -> str | None:
    return _import_error
