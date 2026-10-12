"""Surgically insert Stage 7 worker fencing into existing production files."""

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
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match in {rel}, found {count}")
    path.write_text(text.replace(old, new, 1).replace("\n", newline), encoding="utf-8")
    print("patched", label)


def main() -> None:
    must_replace(
        "app/services/message_schedule_service.py",
        """                # Send message via Telegram
                if account_id and chat_id:
                    success = await _send_message_via_telegram(
""",
        '''                # Send message via Telegram
                if account_id and chat_id:
                    from services.runtime_ownership import legacy_worker_should_handle_account

                    if not await legacy_worker_should_handle_account(str(account_id)):
                        await session.execute(
                            text(
                                """
                                UPDATE message_schedules
                                SET status = 'pending', updated_at = NOW()
                                WHERE id = CAST(:id AS uuid)
                                """
                            ),
                            {"id": message_id},
                        )
                        await session.commit()
                        stats["skipped_runtime_owned"] = 1
                        log.bind(message_id=message_id).info(
                            "message_schedule_service.tick.skip_runtime_owned"
                        )
                        return stats
                    success = await _send_message_via_telegram(
''',
        "message schedule fencing",
    )
    must_replace(
        "app/services/auto_delivery_worker.py",
        '''    """Send using a specific MTProto account instead of hash routing."""
    try:
        from services.mtproto.peer_resolve import resolve_telethon_peer
''',
        '''    """Send using a specific MTProto account instead of hash routing."""
    from services.runtime_ownership import legacy_worker_should_handle_account

    if not await legacy_worker_should_handle_account(str(account_id)):
        raise PermissionError(f"runtime_owned:{account_id}")
    try:
        from services.mtproto.peer_resolve import resolve_telethon_peer
''',
        "auto delivery send fencing",
    )
    must_replace(
        "app/services/auto_delivery_worker.py",
        """                    log.bind(message_id=message_id, reason=gate_reason).info("auto_delivery_worker.account_gate_defer")
                    return stats
                raw_access_hash = (message.get("metadata") or {}).get("telegram_access_hash")
""",
        """                    log.bind(message_id=message_id, reason=gate_reason).info("auto_delivery_worker.account_gate_defer")
                    return stats
                if preferred_account_id:
                    from services.runtime_ownership import legacy_worker_should_handle_account

                    if not await legacy_worker_should_handle_account(str(preferred_account_id)):
                        await _defer_message_until(
                            session,
                            message_id=message_id,
                            send_at=datetime.now(timezone.utc) + timedelta(seconds=30),
                            reason="runtime_owned_skip_legacy_delivery",
                        )
                        stats["skipped_runtime_owned"] = 1
                        log.bind(message_id=message_id).info(
                            "auto_delivery_worker.tick.skip_runtime_owned"
                        )
                        return stats
                raw_access_hash = (message.get("metadata") or {}).get("telegram_access_hash")
""",
        "auto delivery tick fencing",
    )
    must_replace(
        "app/services/auto_delivery_worker.py",
        """                if chat_id:
                    success = await _send_via_account_pool(
                        user_id=user_id,
                        chat_id=chat_id,
                        content=content,
                        trace_id=trace_id,
                        preferred_account_id=preferred_account_id,
                        telegram_access_hash=telegram_access_hash,
                        asset=asset,
                    )

                    if success:
""",
        """                if chat_id:
                    try:
                        success = await _send_via_account_pool(
                            user_id=user_id,
                            chat_id=chat_id,
                            content=content,
                            trace_id=trace_id,
                            preferred_account_id=preferred_account_id,
                            telegram_access_hash=telegram_access_hash,
                            asset=asset,
                        )
                    except PermissionError:
                        await _defer_message_until(
                            session,
                            message_id=message_id,
                            send_at=datetime.now(timezone.utc) + timedelta(seconds=30),
                            reason="runtime_owned_skip_legacy_delivery",
                        )
                        stats["skipped_runtime_owned"] = 1
                        log.bind(message_id=message_id).info(
                            "auto_delivery_worker.tick.skip_runtime_owned"
                        )
                        return stats

                    if success:
""",
        "auto delivery pool permission",
    )
    must_replace(
        "app/services/fixed_auto_reply_service.py",
        """    async def _send_account_jobs(account_id: str, account_jobs: list[dict[str, Any]]) -> tuple[int, int]:
        async with semaphore:
""",
        '''    async def _send_account_jobs(account_id: str, account_jobs: list[dict[str, Any]]) -> tuple[int, int]:
        from services.runtime_ownership import legacy_worker_should_handle_account

        if account_id != "unknown" and not await legacy_worker_should_handle_account(account_id):
            logger.bind(account_id=account_id).info("fixed_auto_reply.skip_runtime_owned")
            ids = [str(job.get("id")) for job in account_jobs if job.get("id")]
            if ids:
                async with AsyncSessionLocal() as skip_db:
                    for job_id in ids:
                        await skip_db.execute(
                            text(
                                """
                                UPDATE fixed_auto_reply_jobs
                                   SET status = 'pending',
                                       failure_reason = 'runtime_owned',
                                       updated_at = NOW()
                                 WHERE id = CAST(:id AS uuid)
                                   AND status = 'sending'
                                """
                            ),
                            {"id": job_id},
                        )
                    await skip_db.commit()
            return 0, 0
        async with semaphore:
''',
        "fixed auto reply fencing",
    )
    must_replace(
        "app/services/telegram_user_migration.py",
        """        account_id = UUID(task["target_account_id"])
        client = await telegram_account_manager.get_client(account_id)
""",
        '''        account_id = UUID(task["target_account_id"])
        from services.runtime_ownership import legacy_worker_should_handle_account

        if not await legacy_worker_should_handle_account(str(account_id)):
            logger.bind(account_id=str(account_id)).info(
                "telegram_user_migration.skip_runtime_owned"
            )
            async with AsyncSessionLocal() as db:
                await db.execute(
                    text(
                        """
                        UPDATE telegram_user_migration_tasks
                           SET status = 'pending',
                               attempt_count = GREATEST(attempt_count - 1, 0),
                               next_attempt_at = NOW() + INTERVAL '30 seconds',
                               updated_at = NOW()
                         WHERE id = CAST(:id AS uuid)
                           AND status = 'resolving'
                        """
                    ),
                    {"id": task_id},
                )
                await db.commit()
            return
        client = await telegram_account_manager.get_client(account_id)
''',
        "migration fencing",
    )
    must_replace(
        "app/services/video_reinvite.py",
        """        account_id = UUID(job["account_id"])
        client = await telegram_account_manager.get_client(account_id)
        if client is None:
            raise RuntimeError("account_not_connected")
""",
        '''        account_id = UUID(job["account_id"])
        from services.runtime_ownership import legacy_worker_should_handle_account

        if not await legacy_worker_should_handle_account(str(account_id)):
            logger.bind(job_id=job_id, account_id=str(account_id)).info(
                "video_reinvite.skip_runtime_owned"
            )
            async with AsyncSessionLocal() as db:
                await db.execute(
                    text(
                        """
                        UPDATE video_reinvite_jobs
                           SET status = CASE WHEN round_number > 0 THEN 'sent' ELSE 'scheduled' END,
                               next_send_at = NOW(),
                               updated_at = NOW()
                         WHERE id = CAST(:id AS uuid)
                           AND status = 'sending'
                        """
                    ),
                    {"id": job_id},
                )
                await db.commit()
            return
        client = await telegram_account_manager.get_client(account_id)
        if client is None:
            raise RuntimeError("account_not_connected")
''',
        "video reinvite fencing",
    )
    must_replace(
        "app/services/call_broadcast/worker.py",
        """            {"account_id": account_id, "job_id": job_id},
        )

    max_concurrent = int(getattr(settings, "CALL_BROADCAST_MAX_CONCURRENT_PER_ACCOUNT", 1))
""",
        """            {"account_id": account_id, "job_id": job_id},
        )

    from services.runtime_ownership import legacy_worker_should_handle_account

    if not await legacy_worker_should_handle_account(str(account_id)):
        await requeue_job(session, job_id=job_id, failure_reason="runtime_owned")
        stats["retrying"] = 1
        log.info("call_broadcast_worker.skip_runtime_owned")
        return stats

    max_concurrent = int(getattr(settings, "CALL_BROADCAST_MAX_CONCURRENT_PER_ACCOUNT", 1))
""",
        "call broadcast worker fencing",
    )
    must_replace(
        "app/services/telegram_account_health.py",
        """            for index, row in enumerate(rows):
                account_id = UUID(row["id"])
                client = await telegram_account_manager.get_client(account_id)
""",
        """            for index, row in enumerate(rows):
                account_id = UUID(row["id"])
                from services.runtime_ownership import legacy_worker_should_handle_account

                if not await legacy_worker_should_handle_account(str(account_id)):
                    continue
                client = await telegram_account_manager.get_client(account_id)
""",
        "account health fencing",
    )
    must_replace(
        "app/services/mtproto/account_pool.py",
        """        route = await self.resolve_account(user_id)
        client = await self.client_resolver(route.account_id)
""",
        """        route = await self.resolve_account(user_id)
        from services.runtime_ownership import legacy_worker_should_handle_account

        if not await legacy_worker_should_handle_account(route.account_id):
            raise PermissionError(f"runtime_owned:{route.account_id}")
        client = await self.client_resolver(route.account_id)
""",
        "account pool fencing",
    )
    print("stage7 patches applied")


if __name__ == "__main__":
    main()
