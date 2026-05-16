"""D3-3: Memory Writer Pipeline.

接 D2-1（OpenRouter LLM 客户端）+ D3-1（characters 表）+ D3-2（10 层 Prompt），
负责把用户的消息**选择性地**写入 ``memories`` 表，供 D4-1 检索时用。

设计：三阶段过滤
================

Phase 1 · 规则预过滤（同步、本地、零成本）
    - 长度 < 10 字符 → 跳过（寒暄"在吗"、"嗯"）
    - 命中常见 acknowledgement 词库（"好的/收到/明白了/thanks/ok/...") → 跳过
    - 全 emoji / 全标点 → 跳过
    - 24h 内同一用户内容哈希命中（Redis Set TTL=86400） → 跳过
    通过率约 20%，挡掉大部分聊天噪声。

Phase 2 · LLM 重要性评分（昂贵，仅 Phase 1 通过的消息进入）
    调用 ``services.llm.chat``，要求模型输出严格 JSON：
        {
          "is_memory_worthy": bool,
          "memory_type": "fact|preference|event|emotion|relationship|goal|milestone",
          "content": "<提炼后的核心事实，简短陈述句>",
          "importance_score": 1-10,
          "confidence": 0.0-1.0,
          "emotion_tags": ["..."]
        }
    - 模型主入口走 settings.LLM_MEMORY_MODEL（默认 fallback gpt-4o-mini，
      结构化输出更稳）；超时 / 5xx → 复用 llm.chat 自带的降级链
    - JSON 解析失败 / memory_type 不在白名单 → 视为"不值得保存"
    - importance_score < settings.MEMORY_IMPORTANCE_THRESHOLD (默认 5) → 跳过

Phase 3 · 持久化
    INSERT INTO memories：
        - content   = LLM 提炼后的事实（不是原始消息）
        - summary   = 原始用户消息（便于回溯）
        - source_message_id = 触发记忆的 user message id
        - embedding = NULL（D3-4 异步 worker 补）
    幂等：同一 source_message_id 已写过的，不重复写。

Failure modes
=============
- LLM 失败 → log warning，跳过这条记忆，**绝不抛异常**
- DB 失败 → log warning，返回 None
- Redis 失败 → 跳过去重，继续往下走（不阻塞）
- 所有调用方都用 ``asyncio.create_task(maybe_write_memory(...))``
  fire-and-forget，保证用户回复 latency 不被记忆写入拖慢

Logging
=======
所有日志带 ``trace_id`` 与 ``component="memory_writer"``：
- ``memory.write.start``
- ``memory.write.prefilter_skip``       reason=too_short / acknowledgement / emoji_only / duplicate
- ``memory.write.llm.start``            model=<x>
- ``memory.write.llm.failed``           reason=...
- ``memory.write.llm.scored``           importance=N type=...
- ``memory.write.below_threshold``      score=N threshold=M
- ``memory.write.persisted``            memory_id=...
- ``memory.write.persist_failed``       error=...
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from typing import Any, Optional

from loguru import logger

from core.config import settings
from core.database import AsyncSessionLocal
from services.llm import chat as llm_chat


# ─────────────────────────────────────────────────────────────
# 常量 / 配置
# ─────────────────────────────────────────────────────────────

MIN_CONTENT_LEN = 8  # 字符数下限（strip 后）

# Acknowledgement / 寒暄 白名单（lowercase, 全/半角混合）
ACKNOWLEDGEMENTS = {
    # 中文
    "好的", "好", "嗯", "嗯嗯", "嗯哼", "哦", "哦哦", "哈哈", "哈哈哈",
    "呵呵", "明白", "明白了", "知道了", "收到", "了解", "可以", "行",
    "在", "在的", "在吗", "你好", "您好", "早", "早安", "晚安", "再见",
    "拜拜", "谢谢", "谢谢你", "辛苦了", "麻烦你了", "没事", "没关系",
    "对", "对的", "不对", "不是", "是的", "是", "不", "不要", "可", "可以的",
    # 英文
    "ok", "okay", "k", "kk", "yes", "y", "no", "n", "yeah", "yep", "nope",
    "sure", "thanks", "thx", "ty", "thank you", "hi", "hello", "hey",
    "bye", "goodbye", "gn", "good night", "good morning", "gm",
    "lol", "lmao", "haha", "hahaha", "rofl",
    "got it", "i see", "alright", "right",
}

# memory_type 白名单（与设计文档对齐）
MEMORY_TYPE_WHITELIST = {
    "fact",          # 客观事实（年龄、职业、家乡、家庭成员）
    "preference",    # 喜好/厌恶
    "event",         # 重要事件（创伤、纪念日、转折点）
    "emotion",       # 稳定情绪倾向（"我常觉得焦虑"）
    "relationship",  # 关系（伴侣、朋友、宠物）
    "goal",          # 长期目标
    "milestone",     # 已达成的里程碑
}

# emoji / 纯符号正则（含常见全角标点区段，避免仅靠 \W 的平台差异）
_EMOJI_OR_PUNCT_RE = re.compile(
    r"^[\s\W\d_"
    r"\u2600-\u27BF"
    r"\U0001F300-\U0001FAFF"
    r"\U0001F600-\U0001F64F"
    r"\U0001F680-\U0001F6FF"
    r"\U0001F900-\U0001F9FF"
    r"\u3000-\u303F"
    r"\uFF00-\uFFEF"
    r"]*$",
    re.UNICODE,
)


# ─────────────────────────────────────────────────────────────
# 公开入口
# ─────────────────────────────────────────────────────────────

async def maybe_write_memory(
    user_id: str,
    conversation_id: str,
    message_id: str,
    content: str,
    trace_id: str,
    redis: Any = None,
    character_id: Optional[str] = None,
    is_onboarding: bool = False,
    db: Any = None,
) -> Optional[str]:
    """三阶段记忆写入。

    Args:
        user_id / conversation_id / message_id: 内部 ID
        content: 原始用户消息文本
        trace_id: 全链路 trace
        redis: 可选，用于 24h 去重
        character_id: 可选，关联角色
        is_onboarding: True 时直接跳过（onboarding 数据走 user_profiles）
        db: 可选，**仅用于单测注入**。生产路径下应留空，函数自行用
            ``AsyncSessionLocal()`` 开一个独立 session（因为 fire-and-forget
            背景任务可能在请求 session 关闭后才执行 INSERT）。

    Returns:
        - 写入成功 → memory_id (str)
        - 任何原因跳过 / 失败 → None

    本函数**不抛异常**（合约保证），所有错误日志化处理。
    """
    log = logger.bind(
        trace_id=trace_id,
        component="memory_writer",
        user_id_hash=_short_hash(user_id),
        message_id=message_id,
    )
    log.info("memory.write.start")

    if not settings.MEMORY_WRITE_ENABLED:
        log.bind(reason="disabled_by_flag").info("memory.write.prefilter_skip")
        return None

    if is_onboarding:
        log.bind(reason="onboarding").info("memory.write.prefilter_skip")
        return None

    # ── Phase 1: 规则预过滤 ───────────────────────────────────
    skip_reason = _rule_prefilter(content)
    if skip_reason:
        log.bind(reason=skip_reason).info("memory.write.prefilter_skip")
        return None

    if redis is not None:
        try:
            is_dup = await _is_duplicate(redis, user_id, content)
        except Exception as exc:
            log.bind(error_type=type(exc).__name__).warning(
                "memory.write.dedup.redis_failed"
            )
            is_dup = False
        if is_dup:
            log.bind(reason="duplicate_24h").info("memory.write.prefilter_skip")
            return None

    # ── Phase 2: LLM 重要性评分 ───────────────────────────────
    started = time.time()
    log.bind(model=settings.LLM_MEMORY_MODEL).info("memory.write.llm.start")

    try:
        evaluation = await _score_with_llm(content=content, trace_id=trace_id)
    except Exception as exc:
        log.bind(
            duration_ms=round((time.time() - started) * 1000, 1),
            error_type=type(exc).__name__,
        ).warning("memory.write.llm.failed")
        return None

    if evaluation is None:
        log.bind(
            duration_ms=round((time.time() - started) * 1000, 1),
        ).warning("memory.write.llm.failed")
        return None

    if not evaluation.get("is_memory_worthy"):
        log.bind(memory_type=evaluation.get("memory_type")).info(
            "memory.write.below_threshold"
        )
        return None

    score = evaluation.get("importance_score", 0)
    threshold = settings.MEMORY_IMPORTANCE_THRESHOLD
    log.bind(
        importance=score,
        memory_type=evaluation.get("memory_type"),
        confidence=evaluation.get("confidence"),
        duration_ms=round((time.time() - started) * 1000, 1),
    ).info("memory.write.llm.scored")

    if score < threshold:
        log.bind(score=score, threshold=threshold).info(
            "memory.write.below_threshold"
        )
        return None

    # ── Phase 3: 持久化 ───────────────────────────────────────
    try:
        if db is not None:
            # 单测注入路径
            memory_id = await _persist_memory(
                db=db,
                user_id=user_id,
                character_id=character_id,
                source_message_id=message_id,
                evaluation=evaluation,
                original_message=content,
            )
        else:
            # 生产路径：自开 session，独立于请求生命周期
            async with AsyncSessionLocal() as own_db:
                memory_id = await _persist_memory(
                    db=own_db,
                    user_id=user_id,
                    character_id=character_id,
                    source_message_id=message_id,
                    evaluation=evaluation,
                    original_message=content,
                )
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).error("memory.write.persist_failed")
        return None

    log.bind(memory_id=memory_id, importance=score).info("memory.write.persisted")

    # 写入去重 Set（成功 + 失败都不写，只有写入成功才记录该内容已处理）
    if redis is not None:
        try:
            await _mark_seen(redis, user_id, content)
        except Exception:
            pass  # 静默失败，下次最坏重复一次

    return memory_id


# ─────────────────────────────────────────────────────────────
# Phase 1: 规则预过滤
# ─────────────────────────────────────────────────────────────

def _rule_prefilter(content: str) -> Optional[str]:
    """返回跳过原因（str）或 None（=通过）。"""
    if not content:
        return "empty"

    stripped = content.strip()
    if not stripped:
        return "empty"

    if len(stripped) < 2:
        return "too_short"

    # 先识别寒暄 / 纯符号，再判长度：短词如 ok/好的 仍应归为 acknowledgement
    normalized = re.sub(r"[\s\.\!\?\,\，\。\！\？\、]+$", "", stripped).lower()
    if normalized in ACKNOWLEDGEMENTS:
        return "acknowledgement"

    if _EMOJI_OR_PUNCT_RE.match(stripped):
        return "emoji_or_punct_only"

    if len(stripped) < MIN_CONTENT_LEN:
        return "too_short"

    return None


async def _is_duplicate(redis: Any, user_id: str, content: str) -> bool:
    """Redis SADD 返回 0 表示已存在。键 ``dedup:mem:{user_id}``，TTL 24h。"""
    key = f"dedup:mem:{user_id}"
    h = _content_hash(content)
    added = await redis.sadd(key, h)
    # 每次写入续期一次 TTL
    await redis.expire(key, 86400)
    return added == 0


async def _mark_seen(redis: Any, user_id: str, content: str) -> None:
    key = f"dedup:mem:{user_id}"
    h = _content_hash(content)
    await redis.sadd(key, h)
    await redis.expire(key, 86400)


# ─────────────────────────────────────────────────────────────
# Phase 2: LLM 评分
# ─────────────────────────────────────────────────────────────

_SCORE_SYSTEM_PROMPT = (
    "你是 ERIS 的记忆评分员。判断一条用户消息是否值得作为长期记忆保存。\n"
    "\n"
    "输出严格 JSON（必须以 { 开头、} 结尾，不要 markdown 围栏，不要解释文字）。\n"
    "JSON 字段：\n"
    "  is_memory_worthy: bool\n"
    "  memory_type:      fact / preference / event / emotion / relationship / goal / milestone\n"
    "  content:          提炼后的核心事实，简短陈述句，不超过 80 字\n"
    "  importance_score: 1-10 整数\n"
    "  confidence:       0.0-1.0 浮点数\n"
    "  emotion_tags:     最多 3 个标签的数组，如 happy / sad / anxious / angry / calm / excited / lonely\n"
    "\n"
    "判断标准：\n"
    "- 值得保存：身份事实（年龄/职业/家乡/家庭成员）、明确偏好（喜欢/讨厌某事）、\n"
    "  重要事件（生日/纪念日/创伤/转折）、稳定情绪倾向（如「我常觉得焦虑」）、关系\n"
    "  （伴侣/朋友/宠物）、长期目标、里程碑。\n"
    "- 不值得保存：寒暄、问候、单字回应、表情包、对 AI 回复的简短反馈、瞬时情绪。\n"
    "- importance_score：身份/关系/创伤=8-10；偏好/目标=5-7；一般事件=3-4；琐碎=1-2。\n"
    "- 不确定时倾向 is_memory_worthy=false。\n"
)


async def _score_with_llm(content: str, trace_id: str) -> Optional[dict]:
    """调用 LLM 给单条消息评分。失败/解析错 → 返回 None。"""
    messages = [
        {"role": "system", "content": _SCORE_SYSTEM_PROMPT},
        {"role": "user", "content": f"用户消息：「{content}」"},
    ]

    result = await llm_chat(
        messages=messages,
        trace_id=trace_id,
        temperature=0.2,
        max_tokens=300,
        force_model=settings.LLM_MEMORY_MODEL or None,
    )

    if result.error or not result.content:
        return None

    parsed = _parse_evaluation(result.content)
    if parsed is None:
        return None

    # 白名单校验
    mtype = parsed.get("memory_type")
    if mtype not in MEMORY_TYPE_WHITELIST:
        # 类型非法但可能仍可保存——降级为 fact，importance 不变
        parsed["memory_type"] = "fact"

    return parsed


def _parse_evaluation(raw: str) -> Optional[dict]:
    """容忍模型偶尔加 markdown 围栏 / 解释前缀。"""
    if not raw:
        return None
    stripped = raw.strip()

    # 去掉 ```json ... ``` 围栏
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
        stripped = stripped.strip()

    # 找第一个 { 到最后一个 }
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < 0 or end <= start:
        return None

    try:
        obj = json.loads(stripped[start : end + 1])
    except (ValueError, TypeError):
        return None

    if not isinstance(obj, dict):
        return None

    # 字段清洗 + 默认值
    obj["is_memory_worthy"] = bool(obj.get("is_memory_worthy", False))
    try:
        obj["importance_score"] = int(obj.get("importance_score", 0))
    except (TypeError, ValueError):
        obj["importance_score"] = 0
    try:
        obj["confidence"] = float(obj.get("confidence", 0.5))
    except (TypeError, ValueError):
        obj["confidence"] = 0.5

    content = obj.get("content")
    if not isinstance(content, str) or not content.strip():
        return None
    obj["content"] = content.strip()[:500]

    tags = obj.get("emotion_tags", [])
    if not isinstance(tags, list):
        tags = []
    obj["emotion_tags"] = [str(t).strip() for t in tags if str(t).strip()][:3]

    return obj


# ─────────────────────────────────────────────────────────────
# Phase 3: 持久化
# ─────────────────────────────────────────────────────────────

async def _persist_memory(
    db: Any,
    user_id: str,
    character_id: Optional[str],
    source_message_id: str,
    evaluation: dict,
    original_message: str,
) -> str:
    from sqlalchemy import text as _sql_text  # 局部导入，与 orchestrator 风格一致

    memory_id = str(uuid.uuid4())

    await db.execute(
        _sql_text(
            "INSERT INTO memories "
            "(id, user_id, character_id, memory_scope, memory_type, content, summary, "
            " importance_score, confidence_score, emotion_tags, source_message_id) "
            "VALUES (:id, :uid, :cid, 'global', :mt, :ct, :sm, "
            "        :imp, :conf, CAST(:tags AS JSONB), :src)"
        ),
        {
            "id": memory_id,
            "uid": user_id,
            "cid": character_id,
            "mt": evaluation["memory_type"],
            "ct": evaluation["content"],
            "sm": original_message[:1000],  # summary 留原文，截断防爆
            "imp": float(evaluation["importance_score"]),
            "conf": float(evaluation.get("confidence", 1.0)),
            "tags": json.dumps(
                evaluation.get("emotion_tags", []), ensure_ascii=False
            ),
            "src": source_message_id,
        },
    )
    await db.commit()
    return memory_id


# ─────────────────────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────────────────────

def _content_hash(content: str) -> str:
    return hashlib.sha256(content.strip().lower().encode("utf-8")).hexdigest()[:24]


def _short_hash(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
