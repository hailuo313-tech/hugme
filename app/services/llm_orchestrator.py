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
  3) 把这些丢给 ``build_prompt``，得到 messages + 各层日志。
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
from services.llm import chat as llm_chat
from services.prompt_builder import (
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
            渲染 L3 CHARACTER / L4 RELATIONSHIP / L5 USER_PROFILE / L7 STATE / L9 FORMAT。
            为 None 时这些层走"未知/默认"，但 10 层标签仍渲染。

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

    prompt = build_prompt(
        PromptInput(
            user_text=user_text,
            character=character_row,
            profile=profile_row,
            memories=None,  # D4-1 接入后此处传 retrieve 结果
            history=history,
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
        log.bind(error_type=type(exc).__name__).warning("orchestrator.context.load_failed")
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
    return build_prompt(PromptInput(user_text=user_text, history=history)).messages


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
        log.bind(error_type=type(exc).__name__).warning("orchestrator.db.import_failed")
        return None, None

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
        log.bind(error_type=type(exc).__name__).warning("orchestrator.db.character_load_failed")

    try:
        row = (
            await db.execute(
                _sql_text("SELECT * FROM user_profiles WHERE user_id = :uid"),
                {"uid": user_id},
            )
        ).fetchone()
        if row is not None and getattr(row, "_mapping", None) is not None:
            profile_row = dict(row._mapping)
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning("orchestrator.db.profile_load_failed")

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
