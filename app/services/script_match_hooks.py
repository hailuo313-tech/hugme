"""Script match hook registry (P3-20 / C-07).

Eight pipeline hooks from business-flow; P3-20 orchestration will call
``evaluate_script_hook`` before LLM wrap. C-07 provides contract + smoke shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

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
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScriptMatchResult:
    hook: HookName
    matched: bool
    script_ids: list[str]
    degradation: str | None
    script_hit_id: str | None = None


def validate_hook(name: str) -> HookName:
    if name not in SCRIPT_HOOKS:
        raise ValueError(f"unknown script hook: {name}")
    return name  # type: ignore[return-value]


def evaluate_script_hook(ctx: ScriptMatchContext) -> ScriptMatchResult:
    """P3-20 placeholder: returns structured no-match until retrieval wired."""
    validate_hook(ctx.hook)
    stage = ctx.script_match_stage or ctx.hook
    return ScriptMatchResult(
        hook=ctx.hook,
        matched=False,
        script_ids=[],
        degradation="p3_20_retrieval_not_wired",
        script_hit_id=None,
    )


def hook_coverage_contract(hook: HookName) -> dict[str, Any]:
    """Metadata for C-07 coverage matrix."""
    return {
        "hook": hook,
        "label": HOOK_LABELS[hook],
        "contract": "evaluate_script_hook",
        "p3_20_status": "stub",
    }
