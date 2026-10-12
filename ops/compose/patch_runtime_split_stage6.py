"""Surgically insert Stage 6 gateway hooks into existing production files."""

from __future__ import annotations

from pathlib import Path

ROOT = Path("/opt/eris")


def must_replace(rel: str, old: str, new: str, label: str) -> None:
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match in {rel}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("patched", label)


def must_replace_all(rel: str, old: str, new: str, expected: int, label: str) -> None:
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{label}: expected {expected} matches in {rel}, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8")
    print("patched", label, expected)


def main() -> None:
    must_replace(
        "app/api/admin.py",
        "from fastapi import APIRouter, Depends, HTTPException, Query, status\n",
        "from fastapi import APIRouter, Depends, HTTPException, Query, status\nfrom fastapi.responses import JSONResponse\n",
        "admin JSONResponse import",
    )
    must_replace(
        "app/api/admin.py",
        """        peer = await resolve_telethon_peer(
            client,
            chat_id,
            access_hash=resolved_access_hash,
        )
        sent = await send_human_like_message(client, peer, content, policy=policy)

        sent_id = getattr(sent, "id", None)
        return True, str(sent_id) if sent_id is not None else None
""",
        """        peer = await resolve_telethon_peer(
            client,
            chat_id,
            access_hash=resolved_access_hash,
        )
        from services.telegram_command_gateway import submit_telegram_command

        async def _legacy_send():
            sent = await send_human_like_message(client, peer, content, policy=policy)
            sent_id = getattr(sent, "id", None)
            return True, str(sent_id) if sent_id is not None else None

        gated = await submit_telegram_command(
            command_type="send_message",
            account_id=str(resolved_account_id) if resolved_account_id else None,
            legacy_execute=_legacy_send,
            payload={"chat_id": chat_id},
            trace_id=trace_id,
        )
        if gated.accepted_not_sent:
            return False, "accepted_not_sent"
        if not gated.executed:
            return False, gated.reason or "telegram_gateway_rejected"
        return gated.value
""",
        "admin operator send gateway",
    )
    must_replace(
        "app/api/admin.py",
        """    if not sent_ok:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=provider_message_id or "telegram_send_failed",
        )
""",
        """    if not sent_ok:
        if provider_message_id == "accepted_not_sent":
            await db.rollback()
            return JSONResponse(
                status_code=202,
                content={
                    "status": "accepted",
                    "executed": False,
                    "conversation_id": conversation_id,
                },
            )
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=provider_message_id or "telegram_send_failed",
        )
""",
        "admin queued reply 202",
    )

    must_replace(
        "app/api/telegram_accounts.py",
        """        if request.auto_connect:
            await telegram_account_manager.connect_account(account_id)
""",
        """        if request.auto_connect:
            from services.telegram_command_gateway import submit_telegram_command

            async def _legacy_auto_connect():
                return await telegram_account_manager.connect_account(account_id)

            gated = await submit_telegram_command(
                command_type="connect_account",
                account_id=str(account_id),
                legacy_execute=_legacy_auto_connect,
            )
            if gated.accepted_not_sent or not gated.executed:
                return SessionLoginVerifyResponse(
                    account_id=str(account_id),
                    phone=phone,
                    status="accepted" if gated.accepted_not_sent else "disconnected",
                    requires_password=False,
                    message="账号已添加",
                )
""",
        "accounts v1 auto_connect",
    )
    must_replace(
        "app/api/telegram_accounts.py",
        """        account_uuid = UUID(account_id)
        success = await telegram_account_manager.connect_account(account_uuid)

        if success:
""",
        """        account_uuid = UUID(account_id)
        from services.telegram_command_gateway import submit_telegram_command

        async def _legacy_connect():
            return await telegram_account_manager.connect_account(account_uuid)

        gated = await submit_telegram_command(
            command_type="connect_account",
            account_id=str(account_uuid),
            legacy_execute=_legacy_connect,
        )
        if gated.accepted_not_sent:
            return {
                "account_id": account_id,
                "status": "accepted",
                "executed": False,
                "command_id": gated.command_id,
            }
        if gated.reason == "telegram_control_not_on_this_process":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="telegram_control_not_on_this_process",
            )
        success = bool(gated.value)

        if success:
""",
        "accounts connect",
    )
    must_replace(
        "app/api/telegram_accounts.py",
        """        account_uuid = UUID(account_id)
        success = await telegram_account_manager.disconnect_account(account_uuid)

        if success:
            return {
                "account_id": account_id,
                "status": "disconnected",
""",
        """        account_uuid = UUID(account_id)
        from services.telegram_command_gateway import submit_telegram_command

        async def _legacy_disconnect():
            return await telegram_account_manager.disconnect_account(account_uuid)

        gated = await submit_telegram_command(
            command_type="disconnect_account",
            account_id=str(account_uuid),
            legacy_execute=_legacy_disconnect,
        )
        if gated.accepted_not_sent:
            return {
                "account_id": account_id,
                "status": "accepted",
                "executed": False,
                "command_id": gated.command_id,
            }
        if gated.reason == "telegram_control_not_on_this_process":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="telegram_control_not_on_this_process",
            )
        success = bool(gated.value)

        if success:
            return {
                "account_id": account_id,
                "status": "disconnected",
""",
        "accounts disconnect",
    )
    must_replace(
        "app/api/telegram_accounts.py",
        """        account_uuid = UUID(account_id)
        success = await telegram_account_manager.delete_account(account_uuid)

        if success:
            return {
                "account_id": account_id,
                "status": "deleted",
""",
        """        account_uuid = UUID(account_id)
        from services.telegram_command_gateway import submit_telegram_command

        async def _legacy_delete():
            return await telegram_account_manager.delete_account(account_uuid)

        gated = await submit_telegram_command(
            command_type="delete_account",
            account_id=str(account_uuid),
            legacy_execute=_legacy_delete,
        )
        if gated.accepted_not_sent:
            return {
                "account_id": account_id,
                "status": "accepted",
                "executed": False,
                "command_id": gated.command_id,
            }
        if gated.reason == "telegram_control_not_on_this_process":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="telegram_control_not_on_this_process",
            )
        success = bool(gated.value)

        if success:
            return {
                "account_id": account_id,
                "status": "deleted",
""",
        "accounts delete",
    )
    must_replace(
        "app/api/telegram_accounts.py",
        """        result = await telegram_account_manager.sync_connected_account_profiles()
        return {
            "message": "Telegram account profiles synced",
            **result,
        }
""",
        """        from services.telegram_command_gateway import submit_telegram_command

        async def _legacy_sync():
            return await telegram_account_manager.sync_connected_account_profiles()

        gated = await submit_telegram_command(
            command_type="sync_profiles",
            account_id=None,
            legacy_execute=_legacy_sync,
        )
        if gated.accepted_not_sent:
            return {
                "message": "Telegram account profile sync accepted",
                "status": "accepted",
                "executed": False,
                "command_id": gated.command_id,
            }
        if not gated.executed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=gated.reason or "telegram_gateway_rejected",
            )
        result = gated.value or {}
        return {
            "message": "Telegram account profiles synced",
            **result,
        }
""",
        "accounts sync",
    )
    must_replace(
        "app/api/telegram_accounts.py",
        """        results = await telegram_account_manager.connect_all_active_accounts()
        connected_count = sum(1 for success in results.values() if success)
""",
        """        from services.telegram_command_gateway import submit_telegram_command

        async def _legacy_connect_all():
            return await telegram_account_manager.connect_all_active_accounts()

        gated = await submit_telegram_command(
            command_type="connect_account",
            account_id=None,
            legacy_execute=_legacy_connect_all,
        )
        if gated.accepted_not_sent:
            return {
                "status": "accepted",
                "executed": False,
                "command_id": gated.command_id,
            }
        if not gated.executed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=gated.reason or "telegram_gateway_rejected",
            )
        results = gated.value or {}
        connected_count = sum(1 for success in results.values() if success)
""",
        "accounts connect-all",
    )
    must_replace(
        "app/api/telegram_accounts.py",
        """        await telegram_account_manager.disconnect_all_accounts()
        return {
            "message": "All accounts disconnected successfully",
        }
""",
        """        from services.telegram_command_gateway import submit_telegram_command

        async def _legacy_disconnect_all():
            return await telegram_account_manager.disconnect_all_accounts()

        gated = await submit_telegram_command(
            command_type="disconnect_account",
            account_id=None,
            legacy_execute=_legacy_disconnect_all,
        )
        if gated.accepted_not_sent:
            return {
                "status": "accepted",
                "executed": False,
                "command_id": gated.command_id,
            }
        if not gated.executed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=gated.reason or "telegram_gateway_rejected",
            )
        return {
            "message": "All accounts disconnected successfully",
        }
""",
        "accounts disconnect-all",
    )

    must_replace(
        "app/services/call_broadcast/incoming_review.py",
        "from services.call_broadcast.session import reject_inbound_call, run_call_broadcast\n",
        """from services.call_broadcast.session import reject_inbound_call, run_call_broadcast


async def _gated_reject_inbound_call(*, account_id, chat_id, trace_id):
    from services.telegram_command_gateway import submit_telegram_command

    async def _legacy():
        return await reject_inbound_call(
            account_id=account_id,
            chat_id=chat_id,
            trace_id=trace_id,
        )

    return await submit_telegram_command(
        command_type="reject_call",
        account_id=str(account_id),
        legacy_execute=_legacy,
        payload={"chat_id": chat_id},
        trace_id=trace_id,
    )
""",
        "review reject helper",
    )
    must_replace(
        "app/services/call_broadcast/incoming_review.py",
        """        if asset is None:
            return {"ok": False, "reason": "video_asset_not_found"}

    pop_pending_review(job_id)
""",
        '''        if asset is None:
            return {"ok": False, "reason": "video_asset_not_found"}

        from services.runtime_ownership import get_account_ownership
        from services.telegram_command_gateway import submit_telegram_command

        ownership = await get_account_ownership(str(job["account_id"]), db)
        if ownership.is_runtime:
            async def _noop():
                return None

            gated = await submit_telegram_command(
                command_type="answer_call",
                account_id=str(job["account_id"]),
                legacy_execute=_noop,
                payload={
                    "job_id": job_id,
                    "video_asset_id": video_asset_id,
                    "operator_id": operator_id,
                    "chat_id": review.chat_id,
                },
                idempotency_key=f"answer_call:{job_id}",
                trace_id=str(job.get("trace_id") or job_id),
            )
            if not gated.accepted_not_sent:
                return {
                    "ok": False,
                    "reason": gated.reason or "telegram_gateway_rejected",
                }
            await db.execute(
                text(
                    """
                    UPDATE call_broadcast_jobs
                    SET video_asset_id = CAST(:video_asset_id AS uuid),
                        metadata = metadata || CAST(:meta_patch AS jsonb),
                        updated_at = NOW()
                    WHERE id = CAST(:job_id AS uuid)
                      AND status = 'pending_operator'
                    """
                ),
                {
                    "job_id": job_id,
                    "video_asset_id": video_asset_id,
                    "meta_patch": json.dumps(
                        {
                            "operator_id": operator_id,
                            "accepted": True,
                            "queued_for_runtime": True,
                            "command_id": gated.command_id,
                            "video_asset_id": video_asset_id,
                        },
                        ensure_ascii=False,
                    ),
                },
            )
            await db.commit()
            pop_pending_review(job_id)
            return {
                "ok": True,
                "job_id": job_id,
                "status": "accepted",
                "executed": False,
                "command_id": gated.command_id,
            }

    pop_pending_review(job_id)
''',
        "review runtime accept first",
    )
    must_replace(
        "app/services/call_broadcast/incoming_review.py",
        """        playback = await run_call_broadcast(
            account_id=UUID(review.account_id),
            chat_id=int(review.chat_id),
            video_path=str(asset["file_path"]),
            duration_seconds=duration,
            trace_id=trace_id,
            telegram_access_hash=review.access_hash,
        )
""",
        """        from services.telegram_command_gateway import submit_telegram_command

        async def _legacy_answer():
            return await run_call_broadcast(
                account_id=UUID(review.account_id),
                chat_id=int(review.chat_id),
                video_path=str(asset["file_path"]),
                duration_seconds=duration,
                trace_id=trace_id,
                telegram_access_hash=review.access_hash,
            )

        gated = await submit_telegram_command(
            command_type="answer_call",
            account_id=str(review.account_id),
            legacy_execute=_legacy_answer,
            payload={"job_id": job_id, "chat_id": review.chat_id},
            trace_id=trace_id,
        )
        if gated.accepted_not_sent:
            return {
                "ok": True,
                "job_id": job_id,
                "status": "accepted",
                "executed": False,
                "command_id": gated.command_id,
            }
        if not gated.executed:
            raise RuntimeError(gated.reason or "telegram_gateway_rejected")
        playback = gated.value
""",
        "review legacy accept gateway",
    )
    must_replace_all(
        "app/services/call_broadcast/incoming_review.py",
        "await reject_inbound_call(",
        "await _gated_reject_inbound_call(",
        3,
        "review reject calls",
    )

    must_replace(
        "app/services/telegram_session_login.py",
        """        connected = False
        if auto_connect:
            connected = await telegram_account_manager.connect_account(account_id)
""",
        """        connected = False
        if auto_connect:
            from services.telegram_command_gateway import submit_telegram_command

            async def _legacy_auto_connect():
                return await telegram_account_manager.connect_account(account_id)

            gated = await submit_telegram_command(
                command_type="connect_account",
                account_id=str(account_id),
                legacy_execute=_legacy_auto_connect,
            )
            connected = bool(gated.executed and gated.value)
""",
        "session login auto_connect",
    )
    print("stage6 patches applied")


if __name__ == "__main__":
    main()
