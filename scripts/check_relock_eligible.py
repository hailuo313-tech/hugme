"""One-off prod diagnostic: post-inbound-video relock eligibility."""
from __future__ import annotations

import asyncio

from sqlalchemy import text

from core.database import AsyncSessionLocal
from services.post_inbound_video_expert_gate import conversation_relock_eligible


async def main() -> None:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT c.id::text, u.external_id
                    FROM conversations c
                    JOIN users u ON u.id = c.user_id
                    WHERE c.post_inbound_video_expert_waived_at IS NOT NULL
                    """
                )
            )
        ).fetchall()
        for conv_id, external_id in rows:
            chat_id = None
            if external_id and str(external_id).startswith("tg_"):
                try:
                    chat_id = int(str(external_id)[3:])
                except ValueError:
                    chat_id = None
            auto_cnt = 0
            inbound_cnt = 0
            if chat_id is not None:
                auto_cnt = (
                    await db.execute(
                        text(
                            """
                            SELECT count(*)
                            FROM call_broadcast_jobs
                            WHERE chat_id = :chat_id
                              AND trigger_source = 'inbound_call'
                              AND status = 'completed'
                              AND COALESCE(metadata->>'source', '') = 'incoming_auto_answer'
                            """
                        ),
                        {"chat_id": chat_id},
                    )
                ).scalar() or 0
                inbound_cnt = (
                    await db.execute(
                        text(
                            """
                            SELECT count(*)
                            FROM call_broadcast_jobs
                            WHERE chat_id = :chat_id
                              AND trigger_source IN ('inbound_call', 'inbound_operator_review')
                              AND status = 'completed'
                            """
                        ),
                        {"chat_id": chat_id},
                    )
                ).scalar() or 0
            eligible = await conversation_relock_eligible(db, conv_id)
            print(
                f"conv={conv_id} ext={external_id} auto={auto_cnt} inbound={inbound_cnt} eligible={eligible}"
            )


if __name__ == "__main__":
    asyncio.run(main())
