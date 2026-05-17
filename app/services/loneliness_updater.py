"""D4-3 / D4-4：根据 ``memories.emotion_tags`` + **当前用户句** 更新 ``loneliness_score``。

D4-3：滑动窗口内结构化记忆的标签聚合 + 向基准衰减（见模块内「记忆」小节）。

D4-4：对 ``user_text`` 做轻量关键词命中（多语言），映射到与 memory_writer 相同的标签集合，
再按 ``LONELINESS_UTTERANCE_MAX_DELTA`` 单独 clamp 后并入总分。**不调用 LLM**，
与记忆 delta 并列；有任一侧非空信号时 **不** 施 D4-3 的基准衰减。

产品规则（与 ``prompt_builder._loneliness_band`` 对齐，0–100 浮点）：
--------------------------------------------------------------------
**记忆信号**
    ``memories``：``is_active=true``、``created_at`` 落在滑动窗口内（默认 30 天），
    最多 ``LONELINESS_MEMORY_CAP`` 条。每条最多 3 个 tag。

**当前句信号（D4-4）**
    关键词子串匹配（ASCII 关键词用大小写不敏感）；命中顺序扫描，最多 3 个不同标签。

**标签权重**（与 D4-3 相同）
    lonely +10, anxious +9, sad +8, angry +3, happy -8, calm -6, excited -4

**记忆聚合**
    每条记忆内 tag 和 → clamp ``±LONELINESS_PER_MEMORY_CLAMP``；跨记忆和 →
    clamp ``±LONELINESS_GLOBAL_DELTA_CLAMP`` → ``delta_tags``。

**当前句聚合**
    ``delta_utterance = clamp(±LONELINESS_UTTERANCE_MAX_DELTA, sum(weights))``。

**基准衰减**
    若**既无**记忆侧非空 tag、**又无**当前句推断出的标签，则
    ``(baseline - old) * LONELINESS_DECAY_FACTOR``。

**更新频率**
    每次 ``generate_reply`` 且 ``db`` + ``user_profiles`` 存在、开关开启时一次；
    在 D4-2 ``retrieve`` 之前执行。

**与 L7**
    写回 ``user_profiles.loneliness_score``；分段阈值不变。
"""
from __future__ import annotations

import json
from typing import Any

from core.config import settings
from services.emotion_lexicon import TAG_WEIGHTS, infer_emotion_tags


def infer_utterance_emotion_tags(user_text: str) -> list[str]:
    """D4-4：从当前用户句推断最多 3 个情绪标签（无 LLM）。"""
    return infer_emotion_tags(user_text, max_tags=3)


def _as_tag_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except (json.JSONDecodeError, TypeError):
            pass
        return [s]
    return []


def compute_next_loneliness(
    old_score: float,
    emotion_tag_rows: list[list[str]],
    *,
    utterance_tags: list[str] | None = None,
    utterance_max_delta: float = 10.0,
    baseline: float,
    per_memory_clamp: float,
    global_clamp: float,
    decay_factor: float,
) -> tuple[float, dict[str, Any]]:
    """纯函数：记忆多行 emotion_tags + 可选当前句标签 → 下一个孤独度。"""
    old_score = max(0.0, min(100.0, float(old_score)))
    baseline = max(0.0, min(100.0, float(baseline)))
    per_memory_clamp = max(0.1, float(per_memory_clamp))
    global_clamp = max(0.1, float(global_clamp))
    decay_factor = max(0.0, min(1.0, float(decay_factor)))
    utterance_max_delta = max(0.0, float(utterance_max_delta))

    utags = [str(x).strip().lower() for x in (utterance_tags or []) if str(x).strip()][:3]

    had_memory_nonempty = False
    for tags in emotion_tag_rows:
        for x in tags[:3]:
            if str(x).strip():
                had_memory_nonempty = True
                break
        if had_memory_nonempty:
            break

    delta_tags = 0.0
    for tags in emotion_tag_rows:
        row_sum = 0.0
        for raw in tags[:3]:
            key = str(raw).strip().lower()
            if not key:
                continue
            row_sum += TAG_WEIGHTS.get(key, 0.0)
        if row_sum > 0:
            row_sum = min(per_memory_clamp, row_sum)
        delta_tags += row_sum

    delta_tags = max(-global_clamp, min(global_clamp, delta_tags))

    utt_sum = sum(TAG_WEIGHTS.get(t, 0.0) for t in utags)
    if utterance_max_delta > 0:
        delta_utterance = max(-utterance_max_delta, min(utterance_max_delta, utt_sum))
    else:
        delta_utterance = 0.0

    had_utterance_signal = bool(utags)
    had_nonempty_tags = had_memory_nonempty or had_utterance_signal

    applied_decay = 0.0
    if not had_nonempty_tags:
        applied_decay = (baseline - old_score) * decay_factor

    new_score = old_score + delta_tags + delta_utterance + applied_decay
    new_score = max(0.0, min(100.0, round(new_score, 2)))

    meta = {
        "delta_tags": round(delta_tags, 3),
        "delta_utterance": round(delta_utterance, 3),
        "utterance_tags": utags,
        "had_memory_nonempty": had_memory_nonempty,
        "had_utterance_signal": had_utterance_signal,
        "had_nonempty_tags": had_nonempty_tags,
        "memories_scanned": len(emotion_tag_rows),
        "applied_decay": round(applied_decay, 4),
    }
    return new_score, meta


async def refresh_loneliness_score(
    *,
    db: Any,
    user_id: str,
    profile_row: dict[str, Any],
    trace_id: str,
    log: Any,
    user_text: str | None = None,
) -> dict[str, Any]:
    """读近期 memories + 可选当前句推断 → 算分 → UPDATE ``user_profiles``。"""
    if not settings.LONELINESS_REFRESH_ENABLED:
        return profile_row

    lookback = max(1, min(int(settings.LONELINESS_LOOKBACK_DAYS or 30), 365))
    cap = max(1, min(int(settings.LONELINESS_MEMORY_CAP or 40), 200))

    raw_old = profile_row.get("loneliness_score")
    try:
        old_score = float(raw_old) if raw_old is not None else float(
            settings.LONELINESS_BASELINE or 35.0
        )
    except (TypeError, ValueError):
        old_score = float(settings.LONELINESS_BASELINE or 35.0)

    baseline = float(settings.LONELINESS_BASELINE or 35.0)
    per_mem = float(settings.LONELINESS_PER_MEMORY_CLAMP or 12.0)
    glob = float(settings.LONELINESS_GLOBAL_DELTA_CLAMP or 20.0)
    decay_f = float(settings.LONELINESS_DECAY_FACTOR or 0.08)
    utt_max = float(settings.LONELINESS_UTTERANCE_MAX_DELTA or 10.0)

    utterance_tags: list[str] | None = None
    if settings.LONELINESS_UTTERANCE_ENABLED and user_text and user_text.strip():
        utterance_tags = infer_utterance_emotion_tags(user_text)

    try:
        from sqlalchemy import text as _sql_text  # type: ignore
    except Exception as exc:  # pragma: no cover
        log.bind(error_type=type(exc).__name__).warning("loneliness.db.import_failed")
        return profile_row

    try:
        result = await db.execute(
            _sql_text(
                """
                SELECT emotion_tags
                FROM memories
                WHERE user_id = CAST(:uid AS uuid)
                  AND is_active = true
                  AND created_at >= NOW() - make_interval(days => :days)
                ORDER BY created_at DESC
                LIMIT :cap
                """
            ),
            {"uid": user_id, "days": lookback, "cap": cap},
        )
        rows = result.fetchall() or []
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning("loneliness.sql.fetch_failed")
        return profile_row

    tag_rows: list[list[str]] = []
    for row in rows:
        m = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
        raw = m.get("emotion_tags")
        tag_rows.append(_as_tag_list(raw))

    new_score, meta = compute_next_loneliness(
        old_score,
        tag_rows,
        utterance_tags=utterance_tags,
        utterance_max_delta=utt_max,
        baseline=baseline,
        per_memory_clamp=per_mem,
        global_clamp=glob,
        decay_factor=decay_f,
    )

    eps = float(settings.LONELINESS_MIN_UPDATE_DELTA or 0.05)
    if abs(new_score - old_score) < eps:
        log.bind(**meta, old_score=old_score, new_score=new_score).info(
            "loneliness.refresh.skip_unchanged"
        )
        return profile_row

    try:
        await db.execute(
            _sql_text(
                """
                UPDATE user_profiles
                SET loneliness_score = :ls,
                    score_updated_at = NOW(),
                    updated_at = NOW()
                WHERE user_id = CAST(:uid AS uuid)
                """
            ),
            {"ls": new_score, "uid": user_id},
        )
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning("loneliness.sql.update_failed")
        return profile_row

    log.bind(
        trace_id=trace_id,
        component="loneliness_updater",
        old_score=old_score,
        new_score=new_score,
        **meta,
    ).info("loneliness.refresh.ok")

    out = dict(profile_row)
    out["loneliness_score"] = new_score
    return out
