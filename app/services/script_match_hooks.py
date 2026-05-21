"""Script match hook registry and orchestration (P3-20/P3-21)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from loguru import logger
from sqlalchemy import text

from services.script_template_retriever import (
    ScriptTemplateQuery,
    search_script_templates,
)

HookName = Literal[
    "inbound",
    "consumption",
    "probe",
    "grading",
    "reply",
    "operator",
    "outbound",
    "archive",
]

SCRIPT_HOOKS: tuple[HookName, ...] = (
    "inbound",
    "consumption",
    "probe",
    "grading",
    "reply",
    "operator",
    "outbound",
    "archive",
)

HOOK_LABELS: dict[HookName, str] = {
    "inbound": "① 入站话术匹配",
    "consumption": "② 消费场景话术匹配",
    "probe": "③ 探测话术匹配",
    "grading": "④ 分级场景话术匹配",
    "reply": "⑤ 回复话术匹配",
    "operator": "⑥ 坐席话术匹配",
    "outbound": "⑦ 出站前话术校验/兜底",
    "archive": "⑧ 归档绑定话术命中记录",
}


@dataclass(frozen=True)
class ScriptMatchContext:
    hook: HookName
    platform: str = "telegram"
    user_level: str = "C"
    intent_id: str | None = None
    user_text: str = ""
    script_match_stage: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    persona_slug: str | None = None
    category_key: str | None = None
    language: str = "zh"
    trace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScriptMatchResult:
    hook: HookName
    matched: bool
    script_ids: list[str]
    degradation: str | None
    script_hit_id: str | None = None
    category_key: str | None = None
    content: str | None = None
    similarity: float | None = None


def validate_hook(name: str) -> HookName:
    if name not in SCRIPT_HOOKS:
        raise ValueError(f"unknown script hook: {name}")
    return name  # type: ignore[return-value]


def evaluate_script_hook(ctx: ScriptMatchContext) -> ScriptMatchResult:
    """Synchronous contract fallback used by older C-07 smoke tests."""
    validate_hook(ctx.hook)
    return ScriptMatchResult(
        hook=ctx.hook,
        matched=False,
        script_ids=[],
        degradation="p3_20_retrieval_not_wired",
        script_hit_id=None,
    )


async def record_script_match_result(
    *,
    db: Any,
    ctx: ScriptMatchContext,
    result: ScriptMatchResult,
) -> str | None:
    """Write one P3-21 audit row for a script-match hook result."""
    if not ctx.conversation_id:
        return None

    hook = validate_hook(ctx.hook)
    metadata = {
        **(ctx.metadata or {}),
        "script_match_stage": ctx.script_match_stage or hook,
        "intent_id": ctx.intent_id,
        "trace_id": ctx.trace_id,
        "similarity": result.similarity,
        "category_key": result.category_key,
    }
    try:
        row = await db.execute(
            text(
                """
                INSERT INTO conversation_script_hits (
                    conversation_id,
                    message_id,
                    hook,
                    script_ids,
                    script_hit_id,
                    matched,
                    degradation,
                    user_level,
                    platform,
                    intent_id,
                    metadata,
                    trace_id,
                    created_at,
                    updated_at
                ) VALUES (
                    CAST(:conversation_id AS uuid),
                    CAST(:message_id AS uuid),
                    :hook,
                    CAST(:script_ids AS jsonb),
                    :script_hit_id,
                    :matched,
                    :degradation,
                    :user_level,
                    :platform,
                    :intent_id,
                    CAST(:metadata AS jsonb),
                    :trace_id,
                    NOW(),
                    NOW()
                )
                RETURNING id
                """
            ),
            {
                "conversation_id": ctx.conversation_id,
                "message_id": ctx.message_id,
                "hook": hook,
                "script_ids": json.dumps(result.script_ids),
                "script_hit_id": result.script_hit_id,
                "matched": result.matched,
                "degradation": result.degradation,
                "user_level": ctx.user_level,
                "platform": ctx.platform,
                "intent_id": ctx.intent_id,
                "metadata": json.dumps(metadata, ensure_ascii=False),
                "trace_id": ctx.trace_id,
            },
        )
        scalar = row.scalar()
        return str(scalar) if scalar is not None else None
    except Exception as exc:
        logger.bind(
            trace_id=ctx.trace_id,
            conversation_id=ctx.conversation_id,
            hook=hook,
            error_type=type(exc).__name__,
        ).warning("script_match.audit_write_failed")
        return None


async def evaluate_script_hook_async(
    ctx: ScriptMatchContext,
    *,
    db: Any | None = None,
    audit: bool = True,
) -> ScriptMatchResult:
    """Run the P3-20 8-hook script retrieval and optionally audit P3-21."""
    hook = validate_hook(ctx.hook)
    if db is None:
        result = ScriptMatchResult(
            hook=hook,
            matched=False,
            script_ids=[],
            degradation="db_not_available",
        )
    else:
        try:
            search = await search_script_templates(
                db=db,
                query=ScriptTemplateQuery(
                    query=ctx.user_text or hook,
                    platform=ctx.platform,
                    user_level=ctx.user_level,
                    persona_slug=ctx.persona_slug,
                    hook=hook,
                    category_key=ctx.category_key,
                    language=ctx.language,
                    limit=3,
                ),
                trace_id=ctx.trace_id,
            )
            if search.hits:
                top = search.hits[0]
                result = ScriptMatchResult(
                    hook=hook,
                    matched=True,
                    script_ids=[hit.id for hit in search.hits],
                    degradation=None,
                    script_hit_id=top.id,
                    category_key=top.category_key,
                    content=top.content,
                    similarity=top.similarity,
                )
            else:
                result = ScriptMatchResult(
                    hook=hook,
                    matched=False,
                    script_ids=[],
                    degradation=search.fallback_reason or "no_script_match",
                )
        except Exception as exc:
            result = ScriptMatchResult(
                hook=hook,
                matched=False,
                script_ids=[],
                degradation=f"script_match_error:{type(exc).__name__}",
            )

    if audit and db is not None:
        await record_script_match_result(db=db, ctx=ctx, result=result)
    return result


async def evaluate_all_script_hooks(
    *,
    db: Any,
    base_context: ScriptMatchContext,
    hooks: tuple[HookName, ...] = SCRIPT_HOOKS,
    audit: bool = True,
) -> list[ScriptMatchResult]:
    """Evaluate all 8 hooks, guaranteeing each has match or degradation."""
    results: list[ScriptMatchResult] = []
    for hook in hooks:
        ctx = ScriptMatchContext(
            hook=hook,
            platform=base_context.platform,
            user_level=base_context.user_level,
            intent_id=base_context.intent_id,
            user_text=base_context.user_text,
            script_match_stage=hook,
            conversation_id=base_context.conversation_id,
            message_id=base_context.message_id,
            persona_slug=base_context.persona_slug,
            category_key=base_context.category_key,
            language=base_context.language,
            trace_id=base_context.trace_id,
            metadata=base_context.metadata,
        )
        results.append(await evaluate_script_hook_async(ctx, db=db, audit=audit))
    return results


def hook_coverage_contract(hook: HookName) -> dict[str, Any]:
    """Metadata for C-07 coverage matrix."""
    return {
        "hook": hook,
        "label": HOOK_LABELS[hook],
        "contract": "evaluate_script_hook",
        "p3_20_status": "retrieval_or_degradation",
    }
