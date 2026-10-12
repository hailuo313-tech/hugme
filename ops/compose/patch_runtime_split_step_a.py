"""Insert Step A ownership guards. Does not start Runtime or write ownership rows."""

from __future__ import annotations

from pathlib import Path

ROOT = Path("/opt/eris")


def _load(rel: str) -> tuple[Path, str, str]:
    path = ROOT / rel
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8").replace("\r\n", "\n")
    return path, text, newline


def must_replace(rel: str, old: str, new: str, label: str) -> None:
    path, text, newline = _load(rel)
    old = old.replace("\r\n", "\n")
    new = new.replace("\r\n", "\n")
    if new.strip() in text and old not in text:
        print("skip", label, "(already present)")
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match in {rel}, found {count}")
    path.write_text(text.replace(old, new, 1).replace("\n", newline), encoding="utf-8")
    print("patched", label)


def main() -> None:
    must_replace(
        "app/services/runtime_ownership.py",
        """async def legacy_worker_should_handle_account(account_id: str | None) -> bool:
    ownership = await get_account_ownership(account_id)
    return legacy_worker_should_handle(ownership)
""",
        """async def legacy_worker_should_handle_account(account_id: str | None) -> bool:
    ownership = await get_account_ownership(account_id)
    return legacy_worker_should_handle(ownership)


async def this_process_may_hold_telegram_session(account_id: str | None) -> bool:
    \"\"\"Whether this process may connect or auto-reply on the account.

    Missing ownership stays legacy. PROCESS_ROLE=all is the current Legacy
    holder and must never steal runtime-owned sessions. telegram_runtime may
    only hold runtime-owned sessions. api and shadow hold none.
    \"\"\"
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
""",
        "ownership hold helper",
    )
    must_replace(
        "app/services/telegram_account_manager.py",
        """    async def connect_account(self, account_id: UUID) -> bool:
        \"\"\"Connect a Telegram account.\"\"\"
        async with self._lock:
""",
        """    async def connect_account(self, account_id: UUID) -> bool:
        \"\"\"Connect a Telegram account.\"\"\"
        from services.runtime_ownership import this_process_may_hold_telegram_session

        if not await this_process_may_hold_telegram_session(str(account_id)):
            logger.info(f"Skip connect; this process must not hold account {account_id}")
            return False
        async with self._lock:
""",
        "connect_account guard",
    )
    must_replace(
        "app/services/mtproto/session_manager.py",
        """            if account.status == "banned":
                logger.warning(f"Skipping banned Telegram account {account.id}")
                continue

            logger.info(f"Restoring session for account {account.id} status={account.status}")
""",
        """            if account.status == "banned":
                logger.warning(f"Skipping banned Telegram account {account.id}")
                continue
            from services.runtime_ownership import this_process_may_hold_telegram_session

            if not await this_process_may_hold_telegram_session(str(account.id)):
                logger.info(f"Skipping restore for account {account.id}; owned by another runtime")
                continue

            logger.info(f"Restoring session for account {account.id} status={account.status}")
""",
        "restore skip",
    )
    must_replace(
        "app/services/mtproto/session_manager.py",
        """        for account in accounts:
            if account.status == "connected":
                client = await telegram_account_manager.get_client(account.id)
""",
        """        for account in accounts:
            from services.runtime_ownership import this_process_may_hold_telegram_session

            if not await this_process_may_hold_telegram_session(str(account.id)):
                continue
            if account.status == "connected":
                client = await telegram_account_manager.get_client(account.id)
""",
        "health skip",
    )
    must_replace(
        "app/services/mtproto/session_manager.py",
        """    async def _handle_disconnect(self, account_id: UUID, reason: str):
        \"\"\"Handle unexpected disconnection.\"\"\"
        logger.warning(f"Handling disconnect for account {account_id}: {reason}")
""",
        """    async def _handle_disconnect(self, account_id: UUID, reason: str):
        \"\"\"Handle unexpected disconnection.\"\"\"
        from services.runtime_ownership import this_process_may_hold_telegram_session

        if not await this_process_may_hold_telegram_session(str(account_id)):
            logger.info(f"Skip disconnect handling for account {account_id}; owned by another runtime")
            return
        logger.warning(f"Handling disconnect for account {account_id}: {reason}")
""",
        "disconnect skip",
    )
    must_replace(
        "app/services/mtproto/session_manager.py",
        """    def _schedule_reconnect(self, account_id: UUID):
        \"\"\"Schedule a reconnection attempt for an account.\"\"\"
        if account_id in self.reconnect_tasks:
            return  # Already scheduled

        logger.info(f"Scheduling reconnect for account {account_id} in {self.reconnect_interval}s")
        task = asyncio.create_task(self._reconnect_with_backoff(account_id))
        self.reconnect_tasks[account_id] = task
""",
        """    def _schedule_reconnect(self, account_id: UUID):
        \"\"\"Schedule a reconnection attempt for an account.\"\"\"
        if account_id in self.reconnect_tasks:
            return  # Already scheduled

        async def _guarded_schedule():
            from services.runtime_ownership import this_process_may_hold_telegram_session

            if not await this_process_may_hold_telegram_session(str(account_id)):
                logger.info(f"Skip reconnect schedule for account {account_id}; owned by another runtime")
                return
            await self._reconnect_with_backoff(account_id)

        logger.info(f"Scheduling reconnect for account {account_id} in {self.reconnect_interval}s")
        task = asyncio.create_task(_guarded_schedule())
        self.reconnect_tasks[account_id] = task
""",
        "reconnect skip",
    )
    must_replace(
        "app/services/mtproto/auto_reply.py",
        """async def handle_mtproto_new_message(client: Any, account_id: uuid.UUID, event: Any) -> None:
    \"\"\"Handle one incoming real-user Telegram message end to end.\"\"\"
    message = getattr(event, "message", event)
""",
        """async def handle_mtproto_new_message(client: Any, account_id: uuid.UUID, event: Any) -> None:
    \"\"\"Handle one incoming real-user Telegram message end to end.\"\"\"
    from services.runtime_ownership import this_process_may_hold_telegram_session

    if not await this_process_may_hold_telegram_session(str(account_id)):
        logger.bind(account_id=str(account_id)).info("mtproto.inbound.skip_runtime_owned")
        return
    message = getattr(event, "message", event)
""",
        "auto_reply skip",
    )
    print("step A patches applied")


if __name__ == "__main__":
    main()
