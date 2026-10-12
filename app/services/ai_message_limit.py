"""Per-user AI outbound caps: T1 users 6, everyone else 20."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from loguru import logger
from sqlalchemy import text

from services.level_engine import load_t1_countries


T1_AI_MESSAGE_LIMIT = 6
NON_T1_AI_MESSAGE_LIMIT = 20
T1_COUNTRY_ASK_WINDOW = 5
T1_HANDOFF_TIMEOUT_SECONDS = 600

# Weak inferences are not "identified country". The first 5 AI messages must
# still ask the user which country they are from.
WEAK_COUNTRY_SOURCES = frozenset({"language_fallback", "telegram_language_code"})

# These are automated/system message sources, not real-time AI chat replies.
# They remain unlimited and must not consume a user's 20-reply AI allowance.
_NON_REALTIME_AI_MODEL_SQL = """
    COALESCE(m.model_name, '') NOT IN (
        'fixed_auto_reply',
        'profile_intake',
        'system_auto_reply',
        'post_auto_answer_profile_prompt',
        'auto_delivery_worker',
        'post_release_ai_followup',
        'user_intent:already_registered',
        'script_asset'
    )
    AND COALESCE(m.model_name, '') NOT LIKE 'post_video_script:%'
"""

# T1 6-cap: only fixed replies, operator replies, and extra media/script deliveries
# are excluded. Country questions (profile_intake) and realtime AI both consume a slot.
_T1_COUNTED_AI_MODEL_SQL = """
    COALESCE(m.model_name, '') <> 'fixed_auto_reply'
    AND COALESCE(m.model_name, '') NOT LIKE 'post_video_script:%'
    AND COALESCE(m.model_name, '') NOT IN (
        'auto_delivery_worker',
        'script_asset'
    )
"""

_QUOTA_SQL = """
                SELECT
                  UPPER(COALESCE(
                    NULLIF(p.country_code, ''),
                    NULLIF(p.preferences->>'country_code', ''),
                    NULLIF(p.preferences->>'stated_country_code', '')
                  )) AS country_code,
                  COALESCE(p.preferences->>'country_source', '') AS country_source,
                  COUNT(m.id) FILTER (
                    WHERE m.sender_type = 'assistant'
                      AND COALESCE(m.content_type, 'text') = 'text'
                      AND COALESCE(m.is_operator_message, FALSE) = FALSE
                      AND """ + _T1_COUNTED_AI_MODEL_SQL + """
                  ) AS system_sent_count,
                  COUNT(m.id) FILTER (
                    WHERE m.sender_type = 'assistant'
                      AND COALESCE(m.content_type, 'text') = 'text'
                      AND COALESCE(m.is_operator_message, FALSE) = FALSE
                      AND """ + _NON_REALTIME_AI_MODEL_SQL + """
                  ) AS realtime_sent_count
                FROM users u
                LEFT JOIN user_profiles p ON p.user_id = u.id
                LEFT JOIN conversations c ON c.user_id = u.id
                LEFT JOIN messages m ON m.conversation_id = c.id
                WHERE u.id = CAST(:user_id AS uuid)
                GROUP BY u.id, p.country_code, p.preferences
"""


@dataclass(frozen=True)
class AIMessageQuota:
    user_id: str
    country_code: str | None
    country_source: str
    country_known: bool
    is_t1: bool
    sent_count: int
    system_sent_count: int
    limit: int

    @property
    def is_sixth_t1_slot(self) -> bool:
        return self.is_t1 and self.sent_count == T1_AI_MESSAGE_LIMIT - 1

    @property
    def must_ask_country(self) -> bool:
        return (not self.country_known) and self.system_sent_count < T1_COUNTRY_ASK_WINDOW


@dataclass(frozen=True)
class AIMessageLimitReached(RuntimeError):
    user_id: str
    sent_count: int
    limit: int = NON_T1_AI_MESSAGE_LIMIT
    is_t1: bool = False

    def __str__(self) -> str:
        kind = "T1" if self.is_t1 else "non-T1"
        return f"{kind} AI message limit reached ({self.sent_count}/{self.limit})"


def _row_values(row: Any) -> Mapping[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "_mapping"):
        return row._mapping
    if isinstance(row, Mapping):
        return row
    return dict(row)


def quota_from_row(user_id: str, values: Mapping[str, Any]) -> AIMessageQuota:
    country_code = str(values.get("country_code") or "").upper() or None
    country_source = str(values.get("country_source") or "").strip()
    country_known = bool(country_code) and country_source not in WEAK_COUNTRY_SOURCES
    is_t1 = bool(country_known and country_code in load_t1_countries())
    system_sent_count = int(values.get("system_sent_count") or 0)
    realtime_sent_count = int(values.get("realtime_sent_count") or 0)
    if is_t1:
        sent_count = system_sent_count
        limit = T1_AI_MESSAGE_LIMIT
    else:
        sent_count = realtime_sent_count
        limit = NON_T1_AI_MESSAGE_LIMIT
    return AIMessageQuota(
        user_id=user_id,
        country_code=country_code,
        country_source=country_source,
        country_known=country_known,
        is_t1=is_t1,
        sent_count=sent_count,
        system_sent_count=system_sent_count,
        limit=limit,
    )


def empty_quota(user_id: str) -> AIMessageQuota:
    return AIMessageQuota(
        user_id=user_id,
        country_code=None,
        country_source="",
        country_known=False,
        is_t1=False,
        sent_count=0,
        system_sent_count=0,
        limit=NON_T1_AI_MESSAGE_LIMIT,
    )


async def inspect_ai_message_quota(
    db: Any,
    *,
    user_id: str,
) -> AIMessageQuota:
    row = (await db.execute(text(_QUOTA_SQL), {"user_id": user_id})).first()
    if row is None:
        return empty_quota(user_id)
    return quota_from_row(user_id, _row_values(row))


async def enforce_ai_message_limit(
    db: Any,
    *,
    user_id: str,
    trace_id: str | None = None,
) -> AIMessageQuota:
    """T1 users stop after 6 AI messages; everyone else stops after 20.

    Unknown/missing/weak country is treated as non-T1. The transaction
    advisory lock prevents two simultaneous replies from both claiming the
    last slot.
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": f"ai-message-cap:{user_id}"},
    )
    quota = await inspect_ai_message_quota(db, user_id=user_id)
    if quota.sent_count < quota.limit:
        return quota
    logger.bind(
        component="ai_message_limit",
        trace_id=trace_id,
        user_id=user_id,
        country_code=quota.country_code,
        is_t1=quota.is_t1,
        sent_count=quota.sent_count,
        limit=quota.limit,
    ).info("ai_message_limit.blocked")
    raise AIMessageLimitReached(
        user_id=user_id,
        sent_count=quota.sent_count,
        limit=quota.limit,
        is_t1=quota.is_t1,
    )


_T1_IDENTIFIED_AT_SQL = """
COALESCE(
  CASE
    WHEN p.preferences->>'t1_identified_at' ~ '^[0-9]'
    THEN CAST(p.preferences->>'t1_identified_at' AS timestamptz)
  END,
  (
    SELECT MIN(m.created_at)
    FROM messages m
    WHERE m.conversation_id = c.id
      AND m.sender_type = 'user'
  ),
  c.created_at
)
"""


async def t1_handoff_elapsed_seconds(db: Any, conversation_id: str) -> float | None:
    row = (
        await db.execute(
            text(
                f"""
                SELECT EXTRACT(EPOCH FROM (NOW() - {_T1_IDENTIFIED_AT_SQL})) AS elapsed
                FROM conversations c
                LEFT JOIN user_profiles p ON p.user_id = c.user_id
                WHERE c.id = CAST(:cid AS uuid)
                """
            ),
            {"cid": conversation_id},
        )
    ).first()
    if row is None:
        return None
    values = _row_values(row)
    raw = values.get("elapsed")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


async def maybe_handoff_t1_after_ai_cap(
    db: Any,
    *,
    user_id: str,
    conversation_id: str,
    trace_id: str | None = None,
) -> bool:
    """Move a T1 thread to waiting-operator after 6 AI messages or 10 minutes."""
    quota = await inspect_ai_message_quota(db, user_id=user_id)
    if not quota.is_t1:
        return False
    reason = "ai_cap"
    if quota.sent_count < T1_AI_MESSAGE_LIMIT:
        elapsed = await t1_handoff_elapsed_seconds(db, conversation_id)
        if elapsed is None or elapsed < T1_HANDOFF_TIMEOUT_SECONDS:
            return False
        reason = "timeout"
    from services.human_takeover_gate import ensure_t1_manual_handoff

    await ensure_t1_manual_handoff(
        db,
        conversation_id=conversation_id,
        user_id=user_id,
    )
    logger.bind(
        component="ai_message_limit",
        trace_id=trace_id,
        user_id=user_id,
        conversation_id=conversation_id,
        country_code=quota.country_code,
        sent_count=quota.sent_count,
        limit=quota.limit,
        handoff_reason=reason,
        timeout_seconds=T1_HANDOFF_TIMEOUT_SECONDS,
    ).info("ai_message_limit.t1_handoff")
    return True


async def list_t1_timeout_handoff_candidates(
    db: Any,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """T1 AI_ACTIVE threads that have not hit 6 replies but passed the 10-minute clock."""
    t1_codes = sorted(load_t1_countries())
    if not t1_codes:
        return []
    rows = (
        await db.execute(
            text(
                f"""
                SELECT
                  c.id::text AS conversation_id,
                  c.user_id::text AS user_id
                FROM conversations c
                JOIN users u ON u.id = c.user_id
                LEFT JOIN user_profiles p ON p.user_id = u.id
                WHERE c.state = 'AI_ACTIVE'
                  AND COALESCE(u.status, 'active') = 'active'
                  AND UPPER(COALESCE(
                    NULLIF(p.country_code, ''),
                    NULLIF(p.preferences->>'country_code', ''),
                    NULLIF(p.preferences->>'stated_country_code', '')
                  )) = ANY(:t1_codes)
                  AND COALESCE(p.preferences->>'country_source', '') NOT IN (
                    'language_fallback', 'telegram_language_code'
                  )
                  AND {_T1_IDENTIFIED_AT_SQL} <= NOW()
                    - (:timeout_seconds * INTERVAL '1 second')
                  AND (
                    SELECT COUNT(*)
                    FROM messages m
                    WHERE m.conversation_id = c.id
                      AND m.sender_type = 'assistant'
                      AND COALESCE(m.content_type, 'text') = 'text'
                      AND COALESCE(m.is_operator_message, FALSE) = FALSE
                      AND {_T1_COUNTED_AI_MODEL_SQL}
                  ) < :ai_limit
                ORDER BY c.updated_at ASC
                LIMIT :limit
                """
            ),
            {
                "t1_codes": t1_codes,
                "timeout_seconds": T1_HANDOFF_TIMEOUT_SECONDS,
                "ai_limit": T1_AI_MESSAGE_LIMIT,
                "limit": max(1, limit),
            },
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def handoff_t1_timeout_candidates(db: Any, *, trace_id: str | None = None) -> int:
    handed = 0
    for row in await list_t1_timeout_handoff_candidates(db):
        moved = await maybe_handoff_t1_after_ai_cap(
            db,
            user_id=str(row["user_id"]),
            conversation_id=str(row["conversation_id"]),
            trace_id=trace_id,
        )
        if moved:
            handed += 1
    return handed