"""POL-01：Policy Service — 七条件自动创建 ``handoff_task``。

规格锚点：``docs/20260514v001.html`` POL-01 / §2.3 真人接管（仓库内无逐条原文时，
以可观测字段落地七条规则，便于运营调参与单测锁定）。

七条（任一命中且通过门控则建单；同轮只建一张单，取最高优先级命中）：

1. **keyword_human** — 用户显式索要真人/人工/客服。
2. **account_risk_level** — ``users.risk_level`` ∈ {high, critical}。
3. **profile_risk_score** — ``user_profiles.risk_score`` ≥ ``POLICY_RISK_SCORE_THRESHOLD``。
4. **loneliness_high** — ``user_profiles.loneliness_score`` ≥ ``POLICY_LONELINESS_THRESHOLD``。
5. **initiation_hot** — ``initiation_score`` ≥ ``trigger_threshold``（与 D4-4 画像分语义对齐）。
6. **vip_tier** — ``user_profiles.vip_level`` ≥ ``POLICY_VIP_LEVEL_THRESHOLD``。
7. **safeguard** — ``users.is_minor_suspected`` 或 ``conversations.handoff_count`` ≥
   ``POLICY_HANDOFF_COUNT_THRESHOLD``（重复接管风暴 / 未成年疑似）。

门控：本会话已有未关闭 handoff、或会话状态不适合自动建单时跳过。
``trigger_reason`` 形如 ``policy:keyword_human``（``VARCHAR(100)`` 内）。
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings

# ── 关键词：显式人工诉求 ─────────────────────────────────────────────

_HUMAN_KEYWORD_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(talk\s+to\s+(a\s+)?human|speak\s+to\s+(a\s+)?human|real\s+person|"
        r"human\s+operator|live\s+agent|customer\s+service\s+agent)\b",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(
        r"(真人|人工客服|转人工|找人工|人工服务|人工在吗|"
        r"我要真人|接人工|客服|找运营|真人客服)",
        re.UNICODE,
    ),
)

_OPEN_HANDOFF_STATUSES = (
    "pending",
    "PENDING",
    "ESCALATED",
    "HUMAN_LOCKED",
    "WAITING_OPERATOR",
)

_SKIP_CONV_STATES = frozenset({"CLOSED", "ESCALATED"})


@dataclass(frozen=True)
class PolicyHit:
    """单次评估的最高优先级命中。"""

    code: str
    priority: str  # P1 / P2 / P3
    wait_operator: bool  # 是否将会话切到 WAITING_OPERATOR


def detect_keyword_human_request(user_text: str) -> bool:
    t = (user_text or "").strip()
    if not t:
        return False
    return any(p.search(t) for p in _HUMAN_KEYWORD_PATTERNS)


def evaluate_policy_hits(
    *,
    user_text: str,
    profile: Mapping[str, Any] | None,
    user_risk_level: str | None,
    is_minor_suspected: bool,
    handoff_count: int,
) -> list[PolicyHit]:
    """纯函数：根据内存中的画像/用户/会话字段列出所有命中（无序）。"""
    hits: list[PolicyHit] = []

    if detect_keyword_human_request(user_text):
        hits.append(
            PolicyHit(code="keyword_human", priority="P1", wait_operator=True)
        )

    rl = (user_risk_level or "normal").strip().lower()
    if rl in ("high", "critical"):
        hits.append(
            PolicyHit(code="account_risk_level", priority="P1", wait_operator=False)
        )

    try:
        hc = int(handoff_count)
    except (TypeError, ValueError):
        hc = 0
    if is_minor_suspected or hc >= int(settings.POLICY_HANDOFF_COUNT_THRESHOLD):
        hits.append(PolicyHit(code="safeguard", priority="P1", wait_operator=True))

    if profile:
        try:
            rs = int(profile.get("risk_score") or 0)
        except (TypeError, ValueError):
            rs = 0
        if rs >= int(settings.POLICY_RISK_SCORE_THRESHOLD):
            hits.append(
                PolicyHit(code="profile_risk_score", priority="P2", wait_operator=False)
            )

        try:
            lonely = float(profile.get("loneliness_score") or 0.0)
        except (TypeError, ValueError):
            lonely = 0.0
        if lonely >= float(settings.POLICY_LONELINESS_THRESHOLD):
            hits.append(
                PolicyHit(code="loneliness_high", priority="P2", wait_operator=False)
            )

        try:
            initiation = float(profile.get("initiation_score") or 0.0)
            threshold = float(profile.get("trigger_threshold") or 0.0)
        except (TypeError, ValueError):
            initiation, threshold = 0.0, 0.0
        if threshold > 0 and initiation >= threshold:
            hits.append(
                PolicyHit(code="initiation_hot", priority="P3", wait_operator=False)
            )

        try:
            vip = int(profile.get("vip_level") or 0)
        except (TypeError, ValueError):
            vip = 0
        if vip >= int(settings.POLICY_VIP_LEVEL_THRESHOLD):
            hits.append(PolicyHit(code="vip_tier", priority="P2", wait_operator=False))

    return hits


def _priority_rank(p: str) -> int:
    return {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(p.upper(), 9)


def pick_best_hit(hits: list[PolicyHit]) -> PolicyHit | None:
    if not hits:
        return None
    # Python sort is stable: for equal priority, preserve rule evaluation order.
    # That keeps explicit human requests ahead of other P1 signals in the same turn.
    return sorted(hits, key=lambda h: _priority_rank(h.priority))[0]


async def _has_open_handoff(db: AsyncSession, conversation_id: str) -> bool:
    row = (
        await db.execute(
            text(
                """
                SELECT 1 FROM handoff_tasks
                WHERE conversation_id = :cid
                  AND closed_at IS NULL
                  AND status = ANY(:statuses)
                LIMIT 1
                """
            ),
            {"cid": conversation_id, "statuses": list(_OPEN_HANDOFF_STATUSES)},
        )
    ).fetchone()
    return row is not None


async def _load_policy_supplement(
    db: AsyncSession, user_id: str, conversation_id: str
) -> tuple[str | None, bool, int, str | None] | None:
    """返回 (user_risk_level, is_minor_suspected, handoff_count, conv_state)。"""
    row = (
        await db.execute(
            text(
                """
                SELECT u.risk_level, u.is_minor_suspected,
                       COALESCE(c.handoff_count, 0) AS handoff_count,
                       c.state
                FROM users u
                JOIN conversations c ON c.id = :cid AND c.user_id = u.id
                WHERE u.id = :uid
                """
            ),
            {"uid": user_id, "cid": conversation_id},
        )
    ).fetchone()
    if row is None:
        return None
    mapping = getattr(row, "_mapping", None)
    if mapping is None:
        return None
    m = dict(mapping)
    hc_raw = m.get("handoff_count")
    try:
        hc = int(hc_raw)
    except (TypeError, ValueError):
        hc = 0
    minor = bool(m.get("is_minor_suspected"))
    rl = m.get("risk_level")
    st = m.get("state")
    return (
        str(rl) if rl is not None else "normal",
        minor,
        hc,
        str(st) if st is not None else None,
    )


async def maybe_create_policy_handoff(
    db: AsyncSession,
    *,
    user_id: str,
    conversation_id: str,
    user_text: str,
    profile_row: Mapping[str, Any] | None,
    trace_id: str | None = None,
) -> str | None:
    """若启用且命中策略则插入 ``handoff_tasks`` 并 ``commit``；返回 task id 或 None。"""
    if not settings.POLICY_SERVICE_ENABLED:
        return None

    log = logger.bind(
        trace_id=trace_id,
        component="policy",
        user_id=user_id,
        conversation_id=conversation_id,
    )

    supplement = await _load_policy_supplement(db, user_id, conversation_id)
    if supplement is None:
        log.warning("policy.context.load_failed")
        return None

    user_risk_level, is_minor_suspected, handoff_count, conv_state = supplement
    if conv_state and conv_state.upper() in _SKIP_CONV_STATES:
        log.bind(conv_state=conv_state).info("policy.skip.conv_state")
        return None

    if await _has_open_handoff(db, conversation_id):
        log.info("policy.skip.open_handoff_exists")
        return None

    hits = evaluate_policy_hits(
        user_text=user_text,
        profile=profile_row,
        user_risk_level=user_risk_level,
        is_minor_suspected=is_minor_suspected,
        handoff_count=handoff_count,
    )
    best = pick_best_hit(hits)
    if best is None:
        return None

    task_id = str(uuid.uuid4())
    trigger = f"policy:{best.code}"
    status = "pending"

    await db.execute(
        text(
            """
            INSERT INTO handoff_tasks (
              id, user_id, conversation_id, priority, trigger_reason, status
            ) VALUES (
              :id, :uid, :cid, :pri, :tr, :st
            )
            """
        ),
        {
            "id": task_id,
            "uid": user_id,
            "cid": conversation_id,
            "pri": best.priority,
            "tr": trigger[:100],
            "st": status,
        },
    )

    if best.wait_operator:
        await db.execute(
            text(
                """
                UPDATE conversations
                SET state = 'WAITING_OPERATOR',
                    handoff_count = COALESCE(handoff_count, 0) + 1,
                    updated_at = NOW()
                WHERE id = :cid
                """
            ),
            {"cid": conversation_id},
        )
    else:
        await db.execute(
            text(
                """
                UPDATE conversations
                SET handoff_count = COALESCE(handoff_count, 0) + 1,
                    updated_at = NOW()
                WHERE id = :cid
                """
            ),
            {"cid": conversation_id},
        )

    await db.commit()

    log.bind(
        handoff_task_id=task_id,
        policy_hit=best.code,
        policy_priority=best.priority,
        policy_wait_operator=best.wait_operator,
        all_hits=[h.code for h in hits],
    ).info("policy.handoff.created")

    return task_id
