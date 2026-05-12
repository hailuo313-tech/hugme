"""
D2-2: LLM Orchestrator

封装 generate_reply()：从一条用户消息 → LLM 调用 → 返回回复字符串。

设计要点
--------
- 调用 ``services.llm.chat`` 完成真正的 LLM 请求；不重复造主备/超时/降级逻辑。
- 失败处理
    1. 调用层抛出异常（理论上 ``llm.chat`` 已自吞，仅作防御）→ 视为失败。
    2. ``LLMResult.error`` 非空（``llm.chat`` 内部兜底产物）→ 视为失败。
    3. ``LLMResult.content`` 为空 → 视为失败。
  当 ``settings.LLM_ECHO_FALLBACK`` 为 True 时，失败回退到 ``"echo: <user_text>"``；
  否则抛 ``LLMOrchestratorError``。
- 结构化日志（``ops/observability/logging-spec.md``）
    ``orchestrator.dispatch`` → ``orchestrator.reply`` (happy)
                              → ``orchestrator.llm.error`` / ``.llm.empty`` / ``.llm.exception``
                                → ``orchestrator.fallback`` 或 ``orchestrator.failed``
  所有日志携带 ``trace_id`` 与 ``component="orchestrator"``。
- 本期最小实现仅拼装 system + 当前 user_text；
  Redis 短期上下文（``ctx:{conversation_id}``）接入留 TODO(d2-2.1)。
"""
from __future__ import annotations

import hashlib
import time

from loguru import logger

from core.config import settings
from services.llm import chat as llm_chat


# ── 异常 ──────────────────────────────────────────────

class LLMOrchestratorError(RuntimeError):
    """LLM 编排层错误：上游 LLM 失败且未启用 echo 回退。"""


# ── 常量 ──────────────────────────────────────────────

DEFAULT_SYSTEM_PROMPT = (
    "你是 ERIS 的情感陪伴 AI，名叫 Aria。"
    "用温暖、自然的中文与用户交流，回应要简洁、共情、避免说教。"
)


# ── 公开入口 ──────────────────────────────────────────

async def generate_reply(
    user_id: str,
    conversation_id: str,
    user_text: str,
    trace_id: str,
) -> str:
    """生成一条 AI 回复。

    Args:
        user_id: 内部 user id（调用方应已查/建）。
        conversation_id: 内部 conversation id。
        user_text: 用户最新一条文本。
        trace_id: 全链路 trace id（必填，由调用方传入）。

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
    messages = _build_messages(user_text)

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
    ).info("orchestrator.reply")

    return result.content


# ── 内部 ──────────────────────────────────────────────

def _build_messages(user_text: str) -> list[dict[str, str]]:
    # TODO(d2-2.1): 拼接 Redis ctx:{conversation_id} 的最近 N 条历史消息。
    return [
        {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]


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
