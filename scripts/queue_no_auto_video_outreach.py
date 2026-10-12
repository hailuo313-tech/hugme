from __future__ import annotations

import asyncio
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.database import AsyncSessionLocal
from services.emotion_lexicon import detect_language_from_text


CAMPAIGN_KEY = "no_auto_video_image_invite_20260618"
DELIVERY_MODE = "video_call_outreach"
TRACE_ID = "campaign-no-auto-video-20260618"

ACCOUNT_TARGETS = {
    "6ac4aaf7-237a-42e5-9e43-c85e62152263": 164,  # diliahot_bot
    "b31fe0e5-c25d-4cb9-bf70-94078b94ffec": 120,  # qegh77
    "ac515b28-b8a5-465f-bd13-96306cc53078": 85,   # qegh21
    "578308e1-243d-4ca9-8b0a-e50d759ee0e5": 30,   # zxjk67
    "e3560c35-7c44-4a0b-98f0-e84636eec3d3": 30,   # mary9592
}

ACCOUNT_NAMES = {
    "6ac4aaf7-237a-42e5-9e43-c85e62152263": "diliahot_bot",
    "b31fe0e5-c25d-4cb9-bf70-94078b94ffec": "qegh77",
    "ac515b28-b8a5-465f-bd13-96306cc53078": "qegh21",
    "578308e1-243d-4ca9-8b0a-e50d759ee0e5": "zxjk67",
    "e3560c35-7c44-4a0b-98f0-e84636eec3d3": "mary9592",
}

SUPPORTED_LANGUAGES = {
    "cs", "da", "de", "el", "en", "es", "fi", "fr", "is",
    "it", "ja", "ko", "nl", "no", "pt", "sv", "zh",
}

COPY_BY_LANGUAGE = {
    "en": "I'm home alone and a little bored. I want to video chat with you. Call me when you're ready.",
    "zh": "我一个人在家，很无聊想找你来视频聊天，等你打视频给我哦。",
    "es": "Estoy sola en casa y un poco aburrida. Quiero hacer una videollamada contigo. Llámame cuando estés listo.",
    "pt": "Estou sozinha em casa e meio entediada. Quero fazer uma videochamada com você. Me chama quando estiver pronto.",
    "ja": "今ひとりで家にいて少し退屈。あなたとビデオ通話したいから、準備できたらかけてね。",
    "ko": "나 지금 집에 혼자 있어서 좀 심심해. 너랑 영상통화하고 싶어. 준비되면 전화해 줘.",
    "fr": "Je suis seule à la maison et je m'ennuie un peu. J'ai envie de faire un appel vidéo avec toi. Appelle-moi quand tu es prêt.",
    "de": "Ich bin allein zu Hause und mir ist etwas langweilig. Ich möchte mit dir videochatten. Ruf mich an, wenn du bereit bist.",
    "it": "Sono a casa da sola e mi sto annoiando un po'. Voglio fare una videochiamata con te. Chiamami quando sei pronto.",
    "nl": "Ik ben alleen thuis en verveel me een beetje. Ik wil graag met je videobellen. Bel me wanneer je klaar bent.",
    "sv": "Jag är ensam hemma och har lite tråkigt. Jag vill videochatta med dig. Ring mig när du är redo.",
    "da": "Jeg er alene hjemme og keder mig lidt. Jeg vil gerne videochatte med dig. Ring til mig, når du er klar.",
    "no": "Jeg er alene hjemme og kjeder meg litt. Jeg vil gjerne videochatte med deg. Ring meg når du er klar.",
    "fi": "Olen yksin kotona ja minulla on vähän tylsää. Haluaisin videopuhelun kanssasi. Soita kun olet valmis.",
    "is": "Ég er ein heima og mér leiðist svolítið. Mig langar í myndspjall við þig. Hringdu þegar þú ert tilbúinn.",
    "el": "Είμαι μόνη στο σπίτι και βαριέμαι λίγο. Θέλω να κάνουμε βιντεοκλήση. Κάλεσέ με όταν είσαι έτοιμος.",
    "cs": "Jsem sama doma a trochu se nudím. Chci si s tebou zavolat přes video. Zavolej mi, až budeš připravený.",
}


def _normalize_language(value: Any, recent_text: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw.startswith("zh"):
        return "zh"
    if raw in SUPPORTED_LANGUAGES:
        return raw
    detected = detect_language_from_text(recent_text or "", default="en")
    detected = str(detected or "en").lower()
    if detected.startswith("zh"):
        return "zh"
    return detected if detected in SUPPORTED_LANGUAGES else "en"


def _chat_id_from_external(external_id: str) -> int | None:
    value = str(external_id or "").strip()
    if value.startswith("tg_"):
        value = value[3:]
    try:
        return int(value)
    except ValueError:
        return None


async def _load_assets(session) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                """
                SELECT
                    a.id::text AS id,
                    a.asset_type,
                    a.asset_url,
                    a.storage_path,
                    a.original_filename,
                    a.mime_type,
                    a.file_size_bytes,
                    a.caption
                FROM script_template_assets a
                JOIN script_templates t ON t.id = a.script_template_id
                WHERE a.asset_type = 'image'
                  AND a.is_active = TRUE
                  AND t.status = 'approved'
                ORDER BY a.updated_at DESC, a.created_at DESC
                """
            )
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def _load_candidates(session) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                """
                WITH completed_auto AS (
                    SELECT DISTINCT chat_id
                    FROM call_broadcast_jobs
                    WHERE status = 'completed'
                      AND trigger_source = 'inbound_call'
                      AND chat_id IS NOT NULL
                ),
                latest_conversation AS (
                    SELECT DISTINCT ON (c.user_id)
                        c.user_id,
                        c.id AS conversation_id,
                        c.last_message_at,
                        c.updated_at
                    FROM conversations c
                    ORDER BY c.user_id, COALESCE(c.last_message_at, c.updated_at, c.created_at) DESC
                )
                SELECT
                    u.id::text AS user_id,
                    u.external_id,
                    u.nickname,
                    u.language,
                    lc.conversation_id::text AS conversation_id,
                    COALESCE(lc.last_message_at, lc.updated_at, u.updated_at, u.created_at) AS last_seen_at,
                    last_account.account_id AS assigned_account_id,
                    peer.access_hash,
                    recent.recent_text
                FROM users u
                JOIN latest_conversation lc ON lc.user_id = u.id
                LEFT JOIN LATERAL (
                    SELECT m.sender_id AS account_id
                    FROM messages m
                    WHERE m.conversation_id = lc.conversation_id
                      AND m.sender_type IN ('assistant', 'ai', 'bot')
                      AND m.sender_id ~* '^[0-9a-f-]{36}$'
                    ORDER BY m.created_at DESC
                    LIMIT 1
                ) last_account ON TRUE
                LEFT JOIN LATERAL (
                    SELECT p.access_hash
                    FROM telegram_peer_cache p
                    WHERE p.user_id = u.id
                      AND p.conversation_id = lc.conversation_id
                    ORDER BY p.last_seen_at DESC NULLS LAST, p.updated_at DESC NULLS LAST
                    LIMIT 1
                ) peer ON TRUE
                LEFT JOIN LATERAL (
                    SELECT string_agg(x.content, E'\n' ORDER BY x.created_at DESC) AS recent_text
                    FROM (
                        SELECT m.content, m.created_at
                        FROM messages m
                        WHERE m.conversation_id = lc.conversation_id
                          AND m.sender_type = 'user'
                          AND COALESCE(m.content, '') <> ''
                        ORDER BY m.created_at DESC
                        LIMIT 3
                    ) x
                ) recent ON TRUE
                WHERE u.external_id LIKE 'tg_%'
                  AND COALESCE(u.opt_out_marketing, FALSE) = FALSE
                  AND COALESCE(u.notification_opt_in, TRUE) = TRUE
                  AND (
                      CASE
                          WHEN u.external_id ~ '^tg_[0-9]+$'
                          THEN substring(u.external_id from 4)::bigint
                          ELSE NULL
                      END
                  ) NOT IN (
                      SELECT chat_id FROM completed_auto
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM message_schedules ms
                      WHERE ms.user_id = u.id::text
                        AND ms.metadata->>'campaign_key' = :campaign_key
                        AND ms.status IN ('pending', 'sending', 'sent')
                  )
                ORDER BY COALESCE(lc.last_message_at, lc.updated_at, u.updated_at, u.created_at) DESC
                """
            ),
            {"campaign_key": CAMPAIGN_KEY},
        )
    ).mappings().all()
    candidates: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        chat_id = _chat_id_from_external(str(item.get("external_id") or ""))
        if chat_id is None:
            continue
        item["chat_id"] = chat_id
        candidates.append(item)
    return candidates

def _assign_candidates(candidates: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    assigned = {account_id: [] for account_id in ACCOUNT_TARGETS}
    unassigned: list[dict[str, Any]] = []
    for item in candidates:
        account_id = str(item.get("assigned_account_id") or "")
        if account_id in assigned:
            assigned[account_id].append(item)
        else:
            unassigned.append(item)

    for account_id, target in ACCOUNT_TARGETS.items():
        while len(assigned[account_id]) < target and unassigned:
            item = unassigned.pop(0)
            item["assigned_account_id"] = account_id
            assigned[account_id].append(item)

    account_ids = list(ACCOUNT_TARGETS)
    index = 0
    while unassigned:
        account_id = account_ids[index % len(account_ids)]
        item = unassigned.pop(0)
        item["assigned_account_id"] = account_id
        assigned[account_id].append(item)
        index += 1

    return assigned


async def _insert_schedule(
    session,
    *,
    item: dict[str, Any],
    account_id: str,
    asset: dict[str, Any],
    send_at: datetime,
    batch_no: int,
) -> bool:
    language = _normalize_language(item.get("language"), item.get("recent_text"))
    content = COPY_BY_LANGUAGE.get(language, COPY_BY_LANGUAGE["en"])
    metadata = {
        "delivery_mode": DELIVERY_MODE,
        "campaign_key": CAMPAIGN_KEY,
        "campaign_name": "no_auto_video_image_invite",
        "conversation_id": item.get("conversation_id"),
        "sender_account_id": account_id,
        "telegram_access_hash": str(item["access_hash"]) if item.get("access_hash") is not None else None,
        "language": language,
        "asset": asset,
        "batch_no": batch_no,
        "stop_if_auto_video_completed": True,
    }
    result = await session.execute(
        text(
            """
            INSERT INTO message_schedules (
                user_id, external_user_id, message_type, content, platform, chat_id,
                account_id, status, send_at, priority, metadata, trace_id
            )
            SELECT
                CAST(:user_id AS varchar), CAST(:external_user_id AS varchar),
                CAST(:message_type AS varchar), :content,
                'telegram_real_user', :chat_id, CAST(:account_id AS varchar), 'pending', :send_at,
                :priority, CAST(:metadata AS jsonb), :trace_id
            WHERE NOT EXISTS (
                SELECT 1
                FROM message_schedules
                WHERE user_id = CAST(:user_id AS varchar)
                  AND metadata->>'campaign_key' = :campaign_key
                  AND status IN ('pending', 'sending', 'sent')
            )
            RETURNING id
            """
        ),
        {
            "user_id": item["user_id"],
            "external_user_id": item["external_id"],
            "message_type": "video_call_outreach",
            "content": content,
            "chat_id": item["chat_id"],
            "account_id": account_id,
            "send_at": send_at,
            "priority": 90,
            "metadata": json.dumps(metadata, ensure_ascii=False),
            "trace_id": TRACE_ID,
            "campaign_key": CAMPAIGN_KEY,
        },
    )
    return result.fetchone() is not None


async def main() -> None:
    async with AsyncSessionLocal() as session:
        assets = await _load_assets(session)
        if not assets:
            raise RuntimeError("no active image assets found")

        candidates = await _load_candidates(session)
        assigned = _assign_candidates(candidates)
        now = datetime.now(timezone.utc)
        inserted = 0
        summary: dict[str, dict[str, Any]] = {}

        for account_id, items in assigned.items():
            items.sort(key=lambda row: str(row.get("last_seen_at") or ""), reverse=True)
            for idx, item in enumerate(items):
                batch_no = idx // 30
                send_at = now + timedelta(hours=batch_no)
                asset = assets[(inserted + idx) % len(assets)]
                if await _insert_schedule(
                    session,
                    item=item,
                    account_id=account_id,
                    asset=asset,
                    send_at=send_at,
                    batch_no=batch_no + 1,
                ):
                    inserted += 1
            summary[ACCOUNT_NAMES[account_id]] = {
                "account_id": account_id,
                "users": len(items),
                "batches": math.ceil(len(items) / 30) if items else 0,
            }

        await session.commit()
        print(
            json.dumps(
                {
                    "campaign_key": CAMPAIGN_KEY,
                    "candidates": len(candidates),
                    "inserted": inserted,
                    "assets": len(assets),
                    "summary": summary,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
