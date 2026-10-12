"""Account ownership and generation fencing for the runtime split.

Missing ownership rows are treated as legacy so current production behavior
stays unchanged until a canary switch writes a row.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.process_role import is_shadow_runtime, owns_telegram_runtime


@dataclass(frozen=True)
class AccountOwnership:
    account_id: str | None
    owner: str = "legacy"
    generation: int = 0
    switch_status: str = "stable"

    @property
    def is_runtime(self) -> bool:
        return self.owner == "runtime"

    @property
    def is_legacy(self) -> bool:
        return not self.is_runtime


_lookup: Callable[[str], AccountOwnership | None] | None = None
_ownership_cache: dict[str, tuple[float, AccountOwnership]] = {}
_CACHE_TTL_SECONDS = 5.0


def set_ownership_lookup(lookup: Callable[[str], AccountOwnership | None] | None) -> None:
    global _lookup
    _lookup = lookup


def reset_ownership_runtime_state() -> None:
    _ownership_cache.clear()
    set_ownership_lookup(None)


def looks_like_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        UUID(str(value))
        return True
    except Exception:
        return False


def sql_uuid_or_none(value: Any) -> str | None:
    text_value = "" if value is None else str(value).strip()
    return text_value if looks_like_uuid(text_value) else None


def is_missing_runtime_schema(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    tables = ("runtime_commands", "runtime_events", "telegram_account_ownership")
    return "undefinedtable" in name or (
        "does not exist" in message and any(table in message for table in tables)
    )


def ownership_from_row(account_id: str | None, row: dict | None) -> AccountOwnership:
    if not row:
        return AccountOwnership(account_id=account_id, owner="legacy", generation=0)
    return AccountOwnership(
        account_id=account_id,
        owner=str(row.get("owner") or "legacy"),
        generation=int(row.get("generation") or 0),
        switch_status=str(row.get("switch_status") or "stable"),
    )


def _current_worker_role() -> str:
    from core.process_role import is_shadow_runtime, normalize_process_role, get_runtime_status

    if is_shadow_runtime():
        return "shadow"
    return normalize_process_role(get_runtime_status()["process_role"])


def telegram_worker_advisory_lock_key(base_key: int) -> int:
    """Dedicated Runtime must not share the Legacy worker lock, or ticks stall."""
    if _current_worker_role() == "telegram_runtime":
        return int(base_key) + 1_000_000
    return int(base_key)


def legacy_worker_should_handle(ownership: AccountOwnership | None) -> bool:
    """Whether this process's Telegram workers should execute the account.

    Missing ownership stays legacy. PROCESS_ROLE=all handles legacy only.
    telegram_runtime handles runtime-owned accounts only. api/shadow handle none.
    """
    role = _current_worker_role()
    if role in {"api", "shadow"}:
        return False
    owner = ownership if ownership is not None else AccountOwnership(account_id=None)
    if role == "telegram_runtime":
        return owner.is_runtime
    return owner.is_legacy


def fencing_allows(command_generation: int, ownership: AccountOwnership | None) -> bool:
    if ownership is None:
        return True
    return int(command_generation) >= int(ownership.generation)


def this_process_may_execute_legacy() -> bool:
    if is_shadow_runtime():
        return False
    return owns_telegram_runtime()


def switch_admission(
    *,
    sending: bool = False,
    in_call: bool = False,
    pending_review: bool = False,
    session_complete: bool = True,
    healthy: bool = True,
    generation: int = 1,
) -> dict:
    reasons: list[str] = []
    if sending:
        reasons.append("sending")
    if in_call:
        reasons.append("in_call")
    if pending_review:
        reasons.append("pending_review")
    if not session_complete:
        reasons.append("session_incomplete")
    if not healthy:
        reasons.append("unhealthy")
    return {
        "ok": not reasons,
        "reasons": reasons,
        "next_generation": int(generation) + 1,
    }


async def load_switch_probes(db: AsyncSession, account_id: str) -> dict[str, Any]:
    sending = (
        await db.execute(
            text(
                """
                SELECT EXISTS(
                    SELECT 1 FROM message_schedules
                    WHERE account_id = :account_id AND status = 'sending'
                ) OR EXISTS(
                    SELECT 1 FROM fixed_auto_reply_jobs
                    WHERE account_id = CAST(:account_id AS uuid) AND status IN ('sending', 'claimed')
                ) OR EXISTS(
                    SELECT 1 FROM call_broadcast_jobs
                    WHERE account_id = CAST(:account_id AS uuid)
                      AND status IN ('queued', 'claimed')
                )
                """
            ),
            {"account_id": account_id},
        )
    ).scalar()
    in_call = (
        await db.execute(
            text(
                """
                SELECT EXISTS(
                    SELECT 1 FROM call_broadcast_jobs
                    WHERE account_id = CAST(:account_id AS uuid)
                      AND status IN ('calling', 'ringing', 'active', 'streaming')
                )
                """
            ),
            {"account_id": account_id},
        )
    ).scalar()
    pending_review = (
        await db.execute(
            text(
                """
                SELECT EXISTS(
                    SELECT 1 FROM call_broadcast_jobs
                    WHERE account_id = CAST(:account_id AS uuid)
                      AND status = 'pending_operator'
                )
                """
            ),
            {"account_id": account_id},
        )
    ).scalar()
    account = (
        await db.execute(
            text(
                """
                SELECT session_string IS NOT NULL AND length(session_string) > 20 AS session_complete,
                       COALESCE(status, '') AS status,
                       COALESCE(is_active, false) AS is_active
                FROM telegram_accounts
                WHERE id = CAST(:account_id AS uuid)
                """
            ),
            {"account_id": account_id},
        )
    ).mappings().first()
    ownership = (
        await db.execute(
            text(
                """
                SELECT generation FROM telegram_account_ownership
                WHERE account_id = CAST(:account_id AS uuid)
                """
            ),
            {"account_id": account_id},
        )
    ).mappings().first()
    status = str((account or {}).get("status") or "")
    return {
        "sending": bool(sending),
        "in_call": bool(in_call),
        "pending_review": bool(pending_review),
        "session_complete": bool((account or {}).get("session_complete")),
        "healthy": bool((account or {}).get("is_active")) and status in {"connected", "connecting"},
        "generation": int((ownership or {}).get("generation") or 1),
    }


def _legacy_ownership(account_id: str | None) -> AccountOwnership:
    return AccountOwnership(account_id=account_id, owner="legacy", generation=0)


def _cache_get(account_id: str) -> AccountOwnership | None:
    cached = _ownership_cache.get(account_id)
    if cached is None:
        return None
    stored_at, ownership = cached
    if time.monotonic() - stored_at >= _CACHE_TTL_SECONDS:
        _ownership_cache.pop(account_id, None)
        return None
    return ownership


def _cache_put(account_id: str, ownership: AccountOwnership) -> AccountOwnership:
    _ownership_cache[account_id] = (time.monotonic(), ownership)
    return ownership


async def _fetch_ownership_row(db: AsyncSession, account_id: str) -> AccountOwnership:
    row = (
        await db.execute(
            text(
                """
                SELECT owner, generation, switch_status
                FROM telegram_account_ownership
                WHERE account_id = CAST(:account_id AS uuid)
                """
            ),
            {"account_id": account_id},
        )
    ).mappings().first()
    return ownership_from_row(account_id, dict(row) if row else None)


async def get_account_ownership(
    account_id: str | None,
    db: AsyncSession | None = None,
) -> AccountOwnership:
    if not account_id:
        return _legacy_ownership(None)
    key = str(account_id)
    if _lookup is not None:
        found = _lookup(key)
        return found or _legacy_ownership(key)
    cached = _cache_get(key)
    if cached is not None:
        return cached
    if not looks_like_uuid(key):
        return _cache_put(key, _legacy_ownership(key))
    try:
        if db is not None:
            return _cache_put(key, await _fetch_ownership_row(db, key))
        from core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            return _cache_put(key, await _fetch_ownership_row(session, key))
    except Exception:
        return _cache_put(key, _legacy_ownership(key))


async def claim_account_for_runtime(account_id: str | None) -> AccountOwnership:
    """Persist owner=runtime for API-role processes that can no longer hold sessions.

    Missing and leftover legacy rows are claimed. Existing runtime rows are kept.
    Test lookups do not write to the database.
    """
    current = await get_account_ownership(account_id)
    if not account_id or current.is_runtime:
        return current
    key = str(account_id)
    if not looks_like_uuid(key) or _lookup is not None:
        return current
    generation = max(2, int(current.generation or 0) + 1)
    from core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text(
                    """
                    INSERT INTO telegram_account_ownership (
                        account_id, owner, generation, switch_status
                    )
                    VALUES (CAST(:account_id AS uuid), 'runtime', :generation, 'stable')
                    ON CONFLICT (account_id) DO UPDATE
                    SET owner = 'runtime',
                        generation = GREATEST(
                            telegram_account_ownership.generation + 1,
                            EXCLUDED.generation
                        ),
                        switch_status = 'stable',
                        updated_at = NOW()
                    """
                ),
                {"account_id": key, "generation": generation},
            )
            await db.commit()
    except Exception:
        return current
    _ownership_cache.pop(key, None)
    return await get_account_ownership(key)


async def legacy_worker_should_handle_account(account_id: str | None) -> bool:
    ownership = await get_account_ownership(account_id)
    return legacy_worker_should_handle(ownership)


async def this_process_may_hold_telegram_session(account_id: str | None) -> bool:
    """Whether this process may connect or auto-reply on the account.

    Missing ownership stays legacy. PROCESS_ROLE=all is the current Legacy
    holder and must never steal runtime-owned sessions. telegram_runtime may
    only hold runtime-owned sessions. api and shadow hold none.
    """
    if is_shadow_runtime():
        return False
    try:
        from core.config import settings
        from core.process_role import normalize_process_role

        role = normalize_process_role(getattr(settings, "PROCESS_ROLE", "all"))
    except Exception:
        role = "all"
    if role == "api":
        return False
    ownership = await get_account_ownership(account_id)
    if role == "telegram_runtime":
        return ownership.is_runtime
    return ownership.is_legacy
