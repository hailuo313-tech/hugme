"""
D2-2 / D2-2.1 / D3-2: LLM Orchestrator

封装 ``generate_reply()``：从一条用户消息 → LLM 调用 → 返回回复字符串。

设计要点
--------
- 调用 ``services.llm.chat`` 完成真正的 LLM 请求；不重复造主备/超时/降级逻辑。
- D2-2.1：可选从 Redis ``ctx:{conversation_id}`` 读取最近若干条历史消息，
  与当前 user_text 一起拼成完整 OpenAI 风格 messages。
  读取失败不阻塞主流程，只记录 ``orchestrator.context.load_failed``。
- **D3-2：10 层 Prompt 结构** ——
  组装 messages 的工作交给 ``services.prompt_builder.build_prompt``；
  本模块只负责：
  1) （可选）通过 ``db`` 取该会话的 ``characters`` 行 + 该用户的 ``user_profiles`` 行；
  2) 加载 history（沿用 Redis ctx）；
  3) **D4-3 / D4-4**：在 ``db`` + ``user_profiles`` 行存在时，先于 D4-2 调用
     ``loneliness_updater.refresh_loneliness_score``，用当前 ``user_text`` 写回
     ``loneliness_score``，并用返回的 profile 参与后续 prompt（L7）；
  4) **D4-2**：在 ``MEMORY_RETRIEVE_IN_PROMPT`` 为真且 ``db`` 非空时，用当前 ``user_text``
     调用 ``memory_retriever.retrieve``（参数与 ``POST .../memories/retrieve`` 一致），
     再经 ``memory_consistency`` 过滤与当前句互斥的命中，将剩余 Top-K 写入
     ``PromptInput.memories`` → ``L6_MEMORY``（任务卡 9；默认仅规则、零额外 LLM）；
  5) 把这些丢给 ``build_prompt``，得到 messages + 各层日志。
  缺数据时各层走"未知/默认"降级，但 10 个层标签永远在。
- 失败处理
    1. 调用层抛异常（理论上 ``llm.chat`` 自吞，仅作防御）→ 视为失败。
    2. ``LLMResult.error`` 非空（``llm.chat`` 内部兜底产物）→ 视为失败。
    3. ``LLMResult.content`` 为空 → 视为失败。
  当 ``settings.LLM_ECHO_FALLBACK`` 为 True 时，失败回退到 ``"echo: <user_text>"``；
  否则抛 ``LLMOrchestratorError``。
- 结构化日志（``ops/observability/logging-spec.md``）
    ``orchestrator.dispatch`` → ``orchestrator.context.loaded``（可选）
                              → ``orchestrator.prompt.assembled`` (D3-2)
                              → ``orchestrator.reply`` (happy)
                              → ``orchestrator.llm.error`` / ``.llm.empty`` / ``.llm.exception``
                              → ``orchestrator.fallback`` 或 ``orchestrator.failed``
  所有日志携带 ``trace_id`` 与 ``component="orchestrator"``。
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from loguru import logger

from core.config import settings
from services.loneliness_updater import (
    infer_utterance_emotion_tags,
    refresh_loneliness_score,
)
from services.llm import chat as llm_chat
from services.memory_consistency import filter_memory_hits_for_current_utterance
from services.memory_retriever import retrieve as memory_retrieve
from services.prompt_builder import (
    DEFAULT_SYSTEM_PROMPT,
    LAYER_ORDER,
    PromptInput,
    build_prompt,
)


# ── 异常 ──────────────────────────────────────────────

class LLMOrchestratorError(RuntimeError):
    """LLM 编排层错误：上游 LLM 失败且未启用 echo 回退。"""


# ── 常量 ──────────────────────────────────────────────

# DEFAULT_SYSTEM_PROMPT 从 prompt_builder 重导出，保持老断言兼容：
# = build_prompt(PromptInput(user_text="__placeholder__")).system_content

DEFAULT_HISTORY_LIMIT = 10  # 历史消息默认条数（不含当前消息）


# ── 公开入口 ──────────────────────────────────────────

async def generate_reply(
    user_id: str,
    conversation_id: str,
    user_text: str,
    trace_id: str,
    redis: Any = None,
    history_limit: int = DEFAULT_HISTORY_LIMIT,
    db: Any = None,
    trigger_message_id: str | None = None,
) -> str:
    """生成一条 AI 回复（D3-2 起走 10 层 Prompt 结构）。

    Args:
        user_id: 内部 user id（调用方应已查/建）。
        conversation_id: 内部 conversation id。
        user_text: 用户最新一条文本。
        trace_id: 全链路 trace id（必填）。
        redis: 可选 Redis 客户端（``aioredis.Redis`` 接口）。
            为 None 时不读取历史，仅用当前 user_text。
        history_limit: 历史消息上限（不含当前消息）。
        db: 可选 SQLAlchemy AsyncSession。提供时会加载该会话角色 + 用户画像，
            并在有画像行时先刷新 ``loneliness_score``（D4-3/D4-4），再按需检索记忆（D4-2），
            渲染 L3–L7 / L6 等。为 None 时跳过 DB 相关步骤。
        trigger_message_id: 触发本轮的用户消息 id（危机流程写 risk_events 用）。

    Returns:
        非空字符串。

    Raises:
        LLMOrchestratorError: 上游失败且 ``settings.LLM_ECHO_FALLBACK`` 为 False。
    """
    log = logger.bind(
        trace_id=trace_id,
        component="orchestrator",
        user_id_hash=_short_hash(user_id),
        conversation_id_hash=_short_hash(conversation_id),
    )
    log.info("orchestrator.dispatch")

    if db is not None:
        from services.crisis_intervention import (
            apply_crisis_protocol,
            detect_crisis_in_text,
        )

        if detect_crisis_in_text(user_text):
            crisis = await apply_crisis_protocol(
                db,
                user_id=user_id,
                conversation_id=conversation_id,
                user_text=user_text,
                trigger_message_id=trigger_message_id,
                trace_id=trace_id,
            )
            log.bind(
                risk_event_id=crisis.risk_event_id,
                handoff_task_id=crisis.handoff_task_id,
            ).info("orchestrator.crisis.short_circuit")
            return crisis.safety_reply

    started_at = time.time()

    history: list[dict[str, str]] = []
    if redis is not None and history_limit > 0:
        history = await _load_recent_context(
            redis=redis,
            conversation_id=conversation_id,
            history_limit=history_limit,
            log=log,
        )

    character_row, profile_row = await _load_db_context(db, user_id, conversation_id, log)

    if db is not None and profile_row is not None:
        try:
            profile_row = await refresh_loneliness_score(
                db=db,
                user_id=str(user_id),
                profile_row=profile_row,
                trace_id=trace_id,
                log=log,
                user_text=user_text,
            )
        except Exception as exc:  # pragma: no cover - refresh 内部多已吞异常，防御性
            log.bind(error_type=type(exc).__name__).warning(
                "orchestrator.loneliness_refresh.exception"
            )

        # POL-01：七条件 Policy Service（危机已在上方短路；此处 profile_row 已含最新孤独分）
        if settings.POLICY_SERVICE_ENABLED:
            try:
                from services.policy_service import maybe_create_policy_handoff

                policy_task_id = await maybe_create_policy_handoff(
                    db,
                    user_id=str(user_id),
                    conversation_id=str(conversation_id),
                    user_text=user_text,
                    profile_row=profile_row,
                    trace_id=trace_id,
                )
                if policy_task_id:
                    log.bind(handoff_task_id=policy_task_id).info(
                        "orchestrator.policy.handoff_created"
                    )
            except Exception as exc:  # pragma: no cover - 不阻塞主对话
                log.bind(error_type=type(exc).__name__).warning(
                    "orchestrator.policy.exception"
                )

        # REL-01：S0–S4 自动升降级（S5 不改；成功后 profile_row 供当轮 L4 使用）
        if settings.REL_STAGE_AUTO_ENABLED:
            try:
                from services.relationship_stage_service import (
                    maybe_auto_adjust_relationship_stage,
                )

                new_stage = await maybe_auto_adjust_relationship_stage(
                    db,
                    user_id=str(user_id),
                    profile_row=profile_row,
                    trace_id=trace_id,
                )
                if new_stage:
                    log.bind(relationship_stage=new_stage).info(
                        "orchestrator.relationship_stage.adjusted"
                    )
            except Exception as exc:  # pragma: no cover
                log.bind(error_type=type(exc).__name__).warning(
                    "orchestrator.relationship_stage.exception"
                )

    memories, memory_consistency_dropped = await _maybe_retrieve_memories_for_prompt(
        db=db,
        user_id=user_id,
        user_text=user_text,
        character_row=character_row,
        trace_id=trace_id,
        log=log,
    )

    loneliness_score_log: float | None = None
    if profile_row is not None:
        try:
            ls = profile_row.get("loneliness_score")
            loneliness_score_log = float(ls) if ls is not None else None
        except (TypeError, ValueError):
            loneliness_score_log = None

    loneliness_utterance_tags: list[str] | None = None
    if settings.LONELINESS_UTTERANCE_ENABLED and (user_text or "").strip():
        utags = infer_utterance_emotion_tags(user_text)
        loneliness_utterance_tags = utags if utags else None

    s5_phase_kw: str | None = None
    if db is not None and profile_row is not None:
        try:
            from services.risk_s5 import load_s5_restrictions, relationship_stage_is_s5

            if relationship_stage_is_s5(profile_row):
                s5 = await load_s5_restrictions(
                    db, user_id=str(user_id), profile=profile_row
                )
                if s5.phase is not None:
                    s5_phase_kw = s5.phase.value
                log.bind(s5_phase=s5_phase_kw).info("orchestrator.s5.restrictions_loaded")
        except Exception as exc:  # pragma: no cover
            log.bind(error_type=type(exc).__name__).warning("orchestrator.s5.load_failed")

    prompt = build_prompt(
        PromptInput(
            user_text=user_text,
            character=character_row,
            profile=profile_row,
            memories=memories,
            history=history,
            s5_phase=s5_phase_kw,
        )
    )
    messages = prompt.messages

    log.bind(
        history_count=len(history),
        layers=list(LAYER_ORDER),
        layers_with_data=[k for k, v in prompt.layers.items() if v.strip()],
        system_chars=len(prompt.system_content),
        estimated_tokens=prompt.estimated_tokens,
        has_character=character_row is not None,
        has_profile=profile_row is not None,
        memory_hits=len(memories) if memories else 0,
        memory_consistency_dropped=memory_consistency_dropped,
        loneliness_score=loneliness_score_log,
        loneliness_utterance_tags=loneliness_utterance_tags,
    ).info("orchestrator.prompt.assembled")

    try:
        result = await llm_chat(messages=messages, trace_id=trace_id)
    except Exception as exc:  # pragma: no cover - llm.chat 当前自吞异常，仅防御
        duration_ms = round((time.time() - started_at) * 1000, 1)
        log.bind(
            duration_ms=duration_ms,
            result="failed",
            error_type=type(exc).__name__,
        ).warning("orchestrator.llm.exception")
        return _handle_failure(log, user_text, reason=f"exception:{type(exc).__name__}")

    duration_ms = round((time.time() - started_at) * 1000, 1)

    if result.error:
        log.bind(
            duration_ms=duration_ms,
            model=result.model_used,
            fallback_used=result.fallback_used,
            result="failed",
        ).warning("orchestrator.llm.error")
        return _handle_failure(log, user_text, reason=f"llm_error:{result.error[:80]}")

    if not result.content:
        log.bind(
            duration_ms=duration_ms,
            model=result.model_used,
            result="failed",
        ).warning("orchestrator.llm.empty")
        return _handle_failure(log, user_text, reason="empty_content")

    usage = result.usage or {}
    log.bind(
        duration_ms=duration_ms,
        model=result.model_used,
        fallback_used=result.fallback_used,
        result="success",
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        history_count=len(history),
    ).info("orchestrator.reply")

    return result.content


# ── 内部 ──────────────────────────────────────────────


def _memory_hits_to_prompt_dicts(hits: list[Any]) -> list[dict[str, Any]]:
    """MemoryHit → ``prompt_builder._render_memory`` 所需 dict 列表。"""
    rows: list[dict[str, Any]] = []
    for h in hits:
        rows.append(
            {
                "memory_type": getattr(h, "memory_type", None),
                "content": getattr(h, "content", "") or "",
                "importance_score": getattr(h, "importance_score", None),
            }
        )
    return rows


async def _maybe_retrieve_memories_for_prompt(
    *,
    db: Any,
    user_id: str,
    user_text: str,
    character_row: dict[str, Any] | None,
    trace_id: str,
    log,
) -> tuple[list[dict[str, Any]] | None, int]:
    """D4-2：hybrid retrieve →（可选）一致性过滤 → ``prompt_builder`` 用 dict 列表。

    Returns:
        ``(memories_dicts_or_none, consistency_dropped_count)``
    """
    if not settings.MEMORY_RETRIEVE_IN_PROMPT:
        return None, 0
    if db is None:
        return None, 0
    q = (user_text or "").strip()
    if not q:
        return None, 0

    char_id: str | None = None
    if character_row:
        raw_id = character_row.get("id")
        if raw_id is not None:
            char_id = str(raw_id)

    try:
        result = await memory_retrieve(
            db=db,
            user_id=str(user_id),
            query_text=q,
            k_final=int(settings.MEMORY_RETRIEVE_TOP_K),
            k_candidates=int(settings.MEMORY_RETRIEVE_K_CANDIDATES),
            memory_types=None,
            min_importance=0.0,
            character_id=char_id,
            include_global=True,
            trace_id=trace_id,
            touch_last_used=True,
        )
    except Exception as exc:  # pragma: no cover - retriever 设计上不抛，防御性
        log.bind(error_type=type(exc).__name__).warning("orchestrator.memory_retrieve.exception")
        return None, 0

    if not result.hits:
        return None, 0

    hits: list[Any] = list(result.hits)
    dropped = 0
    if settings.MEMORY_CONSISTENCY_ENABLED:
        hits, dropped = filter_memory_hits_for_current_utterance(q, hits)
        if dropped:
            log.bind(
                component="memory_consistency",
                dropped=dropped,
                kept=len(hits),
            ).info("memory.consistency.filtered")

    if not hits:
        return None, dropped

    return _memory_hits_to_prompt_dicts(hits), dropped


async def _load_recent_context(
    redis: Any,
    conversation_id: str,
    history_limit: int,
    log,
) -> list[dict[str, str]]:
    """读 Redis ``ctx:{conversation_id}`` 最近的历史消息。

    约定：``ctx:{conv_id}`` 用 ``RPUSH`` 写入，最新一条在末尾。每项是 JSON 字符串
    形如 ``{"role": "...", "content": "...", "msg_id": "...", "ts": 123}``。

    实现：取最后 ``history_limit + 1`` 条，丢掉最末一条（视为"当前消息"，
    调用方已显式传入 ``user_text``）；剩下按时间顺序映射为
    ``[{role, content}, ...]``，最多 ``history_limit`` 条。

    任何读取/解析失败都被吞掉，仅 warning，返回空列表。
    """
    key = f"ctx:{conversation_id}"
    try:
        raw_items = await redis.lrange(key, -(history_limit + 1), -1)
    except Exception as exc:  # 网络抖动 / Redis down
        log.bind(error_type=type(exc).__name__).warning(
            "orchestrator.context.load_failed"
        )
        return []

    if not raw_items:
        return []

    # 丢最末一条（当前消息，已由调用方传入 user_text 显式拼）
    history_items = raw_items[:-1] if len(raw_items) > history_limit else raw_items[:-1]
    # 注意：如果 Redis 里不足 limit+1 条，上面也会丢掉最末一条。
    # 这与"用户消息已 push 进 ctx 再调 orchestrator"的语义一致。

    parsed: list[dict[str, str]] = []
    for raw in history_items:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            item = json.loads(raw)
        except (ValueError, TypeError):
            continue

        role = _normalize_role(item.get("role"))
        content = item.get("content")
        if not role or not isinstance(content, str) or not content:
            continue
        parsed.append({"role": role, "content": content})

    return parsed[-history_limit:]


def _normalize_role(role: Any) -> str | None:
    """ERIS 内部 sender_type → OpenAI message.role。"""
    if not isinstance(role, str):
        return None
    role = role.strip().lower()
    if role in ("user",):
        return "user"
    if role in ("assistant", "bot", "ai"):
        return "assistant"
    if role in ("system",):
        return "system"
    return None


def _build_messages(
    user_text: str,
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """[Legacy / 兼容] 老调用方仍可用的一行版本。D3-2 起内部走 prompt_builder。"""
    return build_prompt(
        PromptInput(user_text=user_text, history=history)
    ).messages


async def _load_db_context(
    db: Any,
    user_id: str,
    conversation_id: str,
    log,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """加载 ``characters`` 行 + ``user_profiles`` 行。

    任何查询失败都被吞掉（只 warning），返回 (None, None) 或部分 None；
    prompt_builder 各层会按"未知/默认"降级。
    """
    if db is None:
        return None, None

    character_row: dict[str, Any] | None = None
    profile_row: dict[str, Any] | None = None

    # 局部 import，避免顶层污染（services 层不直接依赖 SQLAlchemy 入口）
    try:
        from sqlalchemy import text as _sql_text  # type: ignore
    except Exception as exc:  # pragma: no cover - 防御
        log.bind(error_type=type(exc).__name__).warning(
            "orchestrator.db.import_failed"
        )
        return None, None

    try:
        row = (
            await db.execute(
                _sql_text(
                    """
                    SELECT p.*, u.language AS language
                    FROM user_profiles p
                    LEFT JOIN users u ON u.id = p.user_id
                    WHERE p.user_id = :uid
                    """
                ),
                {"uid": user_id},
            )
        ).fetchone()
        if row is not None and getattr(row, "_mapping", None) is not None:
            profile_row = dict(row._mapping)
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning(
            "orchestrator.db.profile_load_failed"
        )

    if profile_row is not None and profile_row.get("current_character_id"):
        try:
            row = (
                await db.execute(
                    _sql_text("SELECT * FROM characters WHERE id = :cid"),
                    {"cid": profile_row.get("current_character_id")},
                )
            ).fetchone()
            if row is not None and getattr(row, "_mapping", None) is not None:
                mapping = dict(row._mapping)
                if mapping.get("id") is not None or mapping.get("name") is not None:
                    character_row = mapping
                    log.info("orchestrator.db.character_loaded_from_profile")
        except Exception as exc:
            log.bind(error_type=type(exc).__name__).warning(
                "orchestrator.db.profile_character_load_failed"
            )

    if character_row is None:
        try:
            row = (
                await db.execute(
                    _sql_text(
                        "SELECT ch.* FROM conversations c "
                        "LEFT JOIN characters ch ON ch.id = c.character_id "
                        "WHERE c.id = :cid"
                    ),
                    {"cid": conversation_id},
                )
            ).fetchone()
            if row is not None and getattr(row, "_mapping", None) is not None:
                mapping = dict(row._mapping)
                # 没匹配到 character 时，左联会得到一行但所有 ch.* 为 None
                if mapping.get("id") is not None or mapping.get("name") is not None:
                    character_row = mapping
        except Exception as exc:
            log.bind(error_type=type(exc).__name__).warning(
                "orchestrator.db.character_load_failed"
            )

    return character_row, profile_row


def _echo_fallback(user_text: str) -> str:
    return f"echo: {user_text}"


def _handle_failure(log, user_text: str, reason: str) -> str:
    if settings.LLM_ECHO_FALLBACK:
        log.bind(result="fallback", reason=reason).warning("orchestrator.fallback")
        return _echo_fallback(user_text)
    log.bind(result="failed", reason=reason).error("orchestrator.failed")
    raise LLMOrchestratorError(reason)


def _short_hash(value: str) -> str:
    """SHA-256 前 12 位，用于日志中标识 user/conversation 而不暴露原值。"""
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]

