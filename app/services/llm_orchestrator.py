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
import re
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
from services.conversation_context import load_conversation_context
from services.emotion_lexicon import detect_language_from_text, normalize_language
from services.app_download_conversion import (
    apply_early_link_mandate_overlay,
    clear_last_app_download_decision,
    decision_bypasses_link_cooldown,
    maybe_select_app_download_reply,
)
from services.link_cooldown import (
    is_conversation_link_cooldown_active,
    reply_already_has_link_material,
    strip_links_from_reply,
)
from services.prompt_history import sanitize_history_message_for_prompt
from services.prompt_builder import (
    DEFAULT_SYSTEM_PROMPT,
    LAYER_ORDER,
    PromptInput,
    build_prompt,
)
from services.reply_sanitize import is_generic_ai_refusal, sanitize_outbound_reply
from services.user_request_intent import (
    bypasses_link_cooldown,
    should_skip_download_nudge,
)


# ── 异常 ──────────────────────────────────────────────

class LLMOrchestratorError(RuntimeError):
    """LLM 编排层错误：上游 LLM 失败且未启用 echo 回退。"""


# ── 常量 ──────────────────────────────────────────────

# DEFAULT_SYSTEM_PROMPT 从 prompt_builder 重导出，保持老断言兼容：
# = build_prompt(PromptInput(user_text="__placeholder__")).system_content

DEFAULT_HISTORY_LIMIT = 10  # 历史消息默认条数（不含当前消息）

_LLM_REFUSAL_RETRY_TEMPERATURE = 1.0


def _finalize_reply(text_value: str, *, user_text: str | None = None) -> str:
    return sanitize_outbound_reply(text_value, user_text=user_text)


async def _chat_with_refusal_retry(
    *,
    messages: list[dict],
    trace_id: str,
    log: Any,
) -> Any:
    """Call chat once; on generic model refusal retry with warmer settings + alt provider."""
    result = await llm_chat(
        messages=messages,
        trace_id=trace_id,
        purpose="chat",
        max_tokens=int(getattr(settings, "ORCHESTRATOR_CHAT_MAX_TOKENS", 160) or 160),
    )
    if result.error or not (result.content or "").strip():
        return result
    if not is_generic_ai_refusal(result.content):
        return result

    primary_provider = (settings.LLM_CHAT_PROVIDER or settings.LLM_PROVIDER or "openrouter").strip().lower()
    retry_provider = "openrouter" if primary_provider == "novita" else "novita"
    log.bind(
        primary_model=result.model_used,
        retry_provider=retry_provider,
        retry_temperature=_LLM_REFUSAL_RETRY_TEMPERATURE,
    ).info("orchestrator.refusal.retry")

    retry = await llm_chat(
        messages=messages,
        trace_id=trace_id,
        purpose="chat",
        temperature=_LLM_REFUSAL_RETRY_TEMPERATURE,
        force_model=settings.LLM_FALLBACK_MODEL,
        provider=retry_provider,
        max_tokens=int(getattr(settings, "ORCHESTRATOR_CHAT_MAX_TOKENS", 160) or 160),
    )
    if retry.content and not retry.error and not is_generic_ai_refusal(retry.content):
        log.bind(model=retry.model_used).info("orchestrator.refusal.retry_ok")
        return retry

    log.bind(
        retry_model=retry.model_used,
        retry_error=retry.error,
    ).warning("orchestrator.refusal.retry_failed")
    return result


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
    clear_last_app_download_decision()

    started_at = time.time()

    history: list[dict[str, str]] = []
    context_load_failed = False
    if redis is not None and history_limit > 0:
        history, context_load_failed = await _load_recent_context(
            redis=redis,
            user_id=user_id,
            conversation_id=conversation_id,
            history_limit=history_limit,
            log=log,
        )
        if context_load_failed:
            try:
                from services.business_metrics import business_metrics

                business_metrics.record_orchestrator_context_load(success=False)
            except Exception:
                pass
            log.bind(history_count=0).warning("orchestrator.context.load_failed_active")
        else:
            try:
                from services.business_metrics import business_metrics

                business_metrics.record_orchestrator_context_load(success=True)
            except Exception:
                pass
            if history:
                log.bind(history_count=len(history)).info("orchestrator.context.loaded")

    character_row, profile_row = await _load_db_context(db, user_id, conversation_id, log)

    classified_intent: str | None = None
    if user_text.strip():
        try:
            from services.intent_classifier import classify_intent

            intent_result = classify_intent(user_text, trace_id=trace_id)
            classified_intent = intent_result.primary_intent
            log.bind(
                primary_intent=classified_intent,
                confidence=intent_result.confidence,
            ).info("orchestrator.intent.classified")
            if profile_row is None:
                profile_row = {"current_intent": classified_intent}
            else:
                profile_row = {**profile_row, "current_intent": classified_intent}
        except Exception as exc:  # pragma: no cover
            log.bind(error_type=type(exc).__name__).warning(
                "orchestrator.intent.exception"
            )

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

        if getattr(settings, "VIDEO_REQUEST_OPERATOR_HANDOFF_ENABLED", True):
            # Live video-call reviews are queued in mtproto auto_reply where chat/account exist.
            pass

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
    existing_assistant_reply_count = await _load_existing_assistant_reply_count(
        db=db,
        conversation_id=conversation_id,
        log=log,
    )
    current_assistant_reply_number = (
        existing_assistant_reply_count + 1
        if existing_assistant_reply_count is not None
        else None
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

    link_cooldown_active = False
    if db is not None:
        link_cooldown_active = await is_conversation_link_cooldown_active(
            db,
            conversation_id=conversation_id,
        )

    from services.video_request_handoff import is_live_video_call_request

    if is_live_video_call_request(user_text):
        clear_last_app_download_decision()
        log.bind(video_intent="live_call").info("orchestrator.live_video_call.ack")
        return _finalize_reply(_live_video_call_acknowledgement(user_text), user_text=user_text)

    decision = await maybe_select_app_download_reply(
        db=db,
        user_id=user_id,
        conversation_id=conversation_id,
        user_text=user_text,
        profile_row=profile_row,
        character_row=character_row,
        assistant_reply_count=existing_assistant_reply_count,
        trigger_message_id=trigger_message_id,
        trace_id=trace_id,
        classified_intent=classified_intent,
    )
    decision = await apply_early_link_mandate_overlay(
        db=db,
        user_id=user_id,
        conversation_id=conversation_id,
        user_text=user_text,
        profile_row=profile_row,
        character_row=character_row,
        trigger_message_id=trigger_message_id,
        trace_id=trace_id,
        decision=decision,
    )
    if link_cooldown_active and not bypasses_link_cooldown(user_text):
        if not decision_bypasses_link_cooldown(decision):
            decision = None
            clear_last_app_download_decision()
    if decision is not None:
        log.bind(
            result="success",
            category_key=decision.category_key,
            scene_step=decision.scene_step,
            script_hit_id=decision.script_hit_id,
        ).info("orchestrator.app_download_conversion.nudge_ready")
        if getattr(decision, "intent", None) == "asset_keyword_request":
            return _finalize_reply(_asset_keyword_acknowledgement(user_text, decision), user_text=user_text)

    prompt = build_prompt(
        PromptInput(
            user_text=user_text,
            character=character_row,
            profile=profile_row,
            memories=memories,
            history=history,
            s5_phase=s5_phase_kw,
            current_assistant_reply_number=current_assistant_reply_number,
            context_load_failed=context_load_failed,
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
        assistant_reply_count=existing_assistant_reply_count,
        current_assistant_reply_number=current_assistant_reply_number,
        loneliness_score=loneliness_score_log,
        loneliness_utterance_tags=loneliness_utterance_tags,
        context_load_failed=context_load_failed,
    ).info("orchestrator.prompt.assembled")

    try:
        result = await _chat_with_refusal_retry(messages=messages, trace_id=trace_id, log=log)
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

    reply_text = _finalize_reply(
        _repair_short_preference_interview_followup(user_text, result.content),
        user_text=user_text,
    )
    if link_cooldown_active and not bypasses_link_cooldown(user_text):
        if not decision_bypasses_link_cooldown(decision):
            reply_text = strip_links_from_reply(reply_text)
            log.info("orchestrator.link_cooldown.enforced")
            return reply_text
    return _finalize_reply(
        _append_conservative_download_nudge(reply_text, decision, user_text=user_text),
        user_text=user_text,
    )


# ── 内部 ──────────────────────────────────────────────


_SHORT_ADULT_PREFERENCE_RE = re.compile(
    r"^\s*(doggy|missionary|cowgirl|reverse cowgirl|spooning|rough|slow|hard|soft|"
    r"anal|oral|bj|blowjob|top|bottom|dom|sub|dominant|submissive|from behind)\s*[.!?]*\s*$",
    re.IGNORECASE,
)
_INTERVIEW_FOLLOWUP_RE = re.compile(
    r"\s*(?:what\s+do\s+you\s+like\s+most\s+about\s+it|why\s+do\s+you\s+like\s+that|"
    r"what\s+makes\s+you\s+like\s+that|what\s+do\s+you\s+enjoy\s+about\s+it|"
    r"tell\s+me\s+why\s+you\s+like\s+that)\??\s*$",
    re.IGNORECASE,
)


def _repair_short_preference_interview_followup(user_text: str, reply_text: str) -> str:
    """Trim questionnaire-style follow-ups after short adult preference answers."""
    if not _SHORT_ADULT_PREFERENCE_RE.match(user_text or ""):
        return reply_text
    cleaned = _INTERVIEW_FOLLOWUP_RE.sub("", (reply_text or "").strip()).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned or reply_text


def _append_conservative_download_nudge(
    reply_text: str,
    decision: Any | None,
    *,
    user_text: str = "",
) -> str:
    """方案 A：先保留 AI 对用户问题的自然回答，再轻轻追加下载入口。"""
    if decision is None or should_skip_download_nudge(user_text):
        return reply_text
    nudge = _conservative_download_nudge(decision)
    if not nudge:
        return (reply_text or "").strip()
    base = strip_links_from_reply((reply_text or "").strip())
    if not base:
        return nudge
    if reply_already_has_link_material(base):
        return base
    url = _first_url(nudge)
    if url and url in base:
        return base
    return f"{base} {nudge}"


def _asset_keyword_acknowledgement(user_text: str, decision: Any) -> str:
    asset_types = {str(asset.get("asset_type") or "").lower() for asset in getattr(decision, "assets", [])}
    has_image = "image" in asset_types
    has_video = "video" in asset_types
    if has_image and has_video:
        en = "Sure, I’m sending the photos and video here."
    elif has_image:
        en = "Sure, I’m sending the photos here."
    elif has_video:
        en = "Sure, I’m sending the video here."
    else:
        en = "Sure, I’m sending it here."

    lang = normalize_language(getattr(decision, "language", None) or detect_language_from_text(user_text) or "en")
    translations = {
        "fr": {
            "both": "Oui, je t’envoie les photos et la vidéo ici.",
            "image": "Oui, je t’envoie les photos ici.",
            "video": "Oui, je t’envoie la vidéo ici.",
            "other": "Oui, je t’envoie ça ici.",
        },
        "es": {
            "both": "Sí, te envío las fotos y el video aquí.",
            "image": "Sí, te envío las fotos aquí.",
            "video": "Sí, te envío el video aquí.",
            "other": "Sí, te lo envío aquí.",
        },
        "pt": {
            "both": "Sim, vou te mandar as fotos e o vídeo aqui.",
            "image": "Sim, vou te mandar as fotos aqui.",
            "video": "Sim, vou te mandar o vídeo aqui.",
            "other": "Sim, vou te mandar aqui.",
        },
        "ja": {
            "both": "うん、写真と動画をここに送るね。",
            "image": "うん、写真をここに送るね。",
            "video": "うん、動画をここに送るね。",
            "other": "うん、ここに送るね。",
        },
        "ko": {
            "both": "응, 사진이랑 영상을 여기로 보낼게.",
            "image": "응, 사진을 여기로 보낼게.",
            "video": "응, 영상을 여기로 보낼게.",
            "other": "응, 여기로 보낼게.",
        },
    }
    key = "both" if has_image and has_video else "image" if has_image else "video" if has_video else "other"
    return translations.get(lang, {}).get(key, en)


def _live_video_call_acknowledgement(user_text: str) -> str:
    """Warm holding reply while operator handles the live video call."""
    lang = normalize_language(detect_language_from_text(user_text) or "en")
    translations = {
        "zh": "等一下宝贝，我这就给你打过来。",
        "en": "Give me a sec babe, getting my camera ready for you.",
        "es": "Espera un segundo cariño, estoy preparando la cámara para ti.",
        "pt": "Espera um segundo amor, estou preparando a câmera pra você.",
        "fr": "Attends une seconde chéri, je prépare ma caméra pour toi.",
        "ja": "ちょっと待ってね、今カメラの準備するから。",
        "ko": "잠깐만 기다려, 카메라 준비하고 바로 걸게.",
    }
    return translations.get(lang, translations["en"])


def _conservative_download_nudge(decision: Any) -> str | None:
    url = _first_url(getattr(decision, "content", "") or "")
    if not url:
        return None
    category = str(getattr(decision, "category_key", "") or "").strip()
    if category == "app_download_direct_cta":
        return f"Private app: {url} (code: c5a8we)"
    if category == "app_link_clicked_followup":
        return f"More private here: {url}"
    if category == "app_download_objection":
        return f"Safer on my app: {url}"
    if category == "trust_reassurance":
        return f"My app if you want: {url}"
    return f"Faster on my app: {url} (code: c5a8we)"


def _first_url(text_value: str) -> str | None:
    match = re.search(r"https?://[^\s<>\]\"']+", text_value or "")
    if not match:
        return None
    return match.group(0).rstrip(".,!?;:)")


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


async def _load_existing_assistant_reply_count(
    *,
    db: Any,
    conversation_id: str,
    log,
) -> int | None:
    """Count persisted AI replies so the prompt can identify the current reply ordinal."""
    if db is None:
        return None

    try:
        from sqlalchemy import text as _sql_text  # type: ignore
    except Exception as exc:  # pragma: no cover - 防御
        log.bind(error_type=type(exc).__name__).warning(
            "orchestrator.db.import_failed"
        )
        return None

    try:
        row = (
            await db.execute(
                _sql_text(
                    """
                    SELECT COUNT(*) AS assistant_reply_count
                    FROM messages
                    WHERE conversation_id = :cid
                      AND sender_type IN ('assistant', 'bot', 'ai')
                      AND COALESCE(is_operator_message, FALSE) = FALSE
                    """
                ),
                {"cid": conversation_id},
            )
        ).fetchone()
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning(
            "orchestrator.db.assistant_reply_count_failed"
        )
        return None

    if row is None:
        return None
    try:
        return max(0, int(row[0]))
    except (TypeError, ValueError, IndexError):
        mapping = getattr(row, "_mapping", None)
        if mapping is not None:
            try:
                return max(0, int(mapping.get("assistant_reply_count") or 0))
            except (TypeError, ValueError):
                return None
    return None


async def _load_recent_context(
    redis: Any,
    user_id: str,
    conversation_id: str,
    history_limit: int,
    log,
) -> tuple[list[dict[str, str]], bool]:
    """读 Redis 最近历史消息，优先使用 P1-19 ``conv:{user_id}``。

    新路径：``conv:{user_id}`` 用 ``RPUSH`` 写入，保留最近 50 轮（100 条）。
    兼容路径：``ctx:{conv_id}`` 用 ``RPUSH`` 写入，最新一条在末尾。每项是 JSON 字符串
    形如 ``{"role": "...", "content": "...", "msg_id": "...", "ts": 123}``。

    实现：取最后 ``history_limit + 1`` 条，丢掉最末一条（视为"当前消息"，
    调用方已显式传入 ``user_text``）；剩下按时间顺序映射为
    ``[{role, content}, ...]``，最多 ``history_limit`` 条。

    任何读取/解析失败都被吞掉，仅 warning，返回空列表。
    第二个返回值：是否发生 Redis/解析错误（空历史但无异常时为 False）。
    """
    load_failed = False
    try:
        history = await load_conversation_context(
            redis,
            user_id=user_id,
            limit=history_limit,
            drop_latest=True,
        )
        if history:
            return _sanitize_loaded_history(history, log), False
    except Exception as exc:
        load_failed = True
        log.bind(error_type=type(exc).__name__).warning(
            "orchestrator.conv_context.load_failed"
        )

    key = f"ctx:{conversation_id}"
    try:
        raw_items = await redis.lrange(key, -(history_limit + 1), -1)
    except Exception as exc:  # 网络抖动 / Redis down
        load_failed = True
        log.bind(error_type=type(exc).__name__).warning(
            "orchestrator.context.load_failed"
        )
        return [], True

    if not raw_items:
        return [], load_failed

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
        # 过滤掉历史中包含系统提示泄漏特征的 assistant 消息，避免 LLM 模仿复述
        if role == "assistant" and _is_system_leaked_content(content):
            continue
        parsed.append({"role": role, "content": content})

    return _sanitize_loaded_history(parsed[-history_limit:], log), load_failed


def _sanitize_loaded_history(
    history: list[dict[str, str]],
    log,
) -> list[dict[str, str]]:
    sanitized: list[dict[str, str]] = []
    dropped = 0
    for item in history:
        role = item.get("role") or ""
        content = item.get("content") or ""
        cleaned = sanitize_history_message_for_prompt(role, content)
        if cleaned is None:
            dropped += 1
            continue
        sanitized.append({"role": role, "content": cleaned})
    if dropped:
        log.bind(dropped_history_messages=dropped).info("orchestrator.history.sanitized")
    return sanitized


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
    return "嗯，我在听，你说吧～"


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


# 系统信息泄漏特征前缀列表（assistant 历史消息以这些前缀开头时丢弃）
_SYSTEM_LEAK_PREFIXES: tuple[str, ...] = (
    "（根据角色",
    "(根据角色",
    "（根据profile",
    "（根据系统",
    "[LLM",
    "[服务暂时",
    "echo: ",
)

# 系统信息泄漏特征正则（括号注释出现在回复任意位置均视为污染）
_SYSTEM_LEAK_PATTERN = re.compile(
    r"[（(]"                           # 中文或英文左括号
    r"(?:"
    r"根据角色|根据profile|根据系统"    # "根据XX" 系列
    r"|符合角色|遵守.*角色设定"         # "符合/遵守角色设定"
    r"|回答.*角色|角色设定"             # 含"角色设定"
    r"|L\d+.*角色|L3|L4|L5"            # prompt layer 标签
    r"|避免.*承诺|回答简洁|回答保持"    # 指令性说明
    r")",
    re.DOTALL,
)


def _is_system_leaked_content(content: str) -> bool:
    """检测 assistant 历史消息是否包含系统提示泄漏特征（前缀或正文注释）。"""
    stripped = content.lstrip()
    if any(stripped.startswith(prefix) for prefix in _SYSTEM_LEAK_PREFIXES):
        return True
    if _SYSTEM_LEAK_PATTERN.search(content):
        return True
    return False
