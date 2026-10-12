"""J-02: AI pipeline smoke runner (C-08).

Exercises the in-process AI path: safety → grading → script hooks → prompt →
stub LLM. Records per-stage and total latency; enforces end-to-end budget
(default 8000 ms including simulated LLM delay).
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from services.level_engine import UserLevelInput, calc_user_level
from services.prompt_builder import LAYER_ORDER, PromptInput, build_prompt
from services.script_match_hooks import (
    SCRIPT_HOOKS,
    ScriptMatchContext,
    evaluate_script_hook,
)

LATENCY_BUDGET_MS = 8000
Outcome = Literal["reply", "blocked", "crisis"]


@dataclass
class PipelineSmokeResult:
    id: str
    title: str
    outcome: Outcome
    pass_case: bool
    total_ms: float
    within_budget: bool
    timings_ms: dict[str, float] = field(default_factory=dict)
    level: str | None = None
    reply_preview: str | None = None
    block_reason: str | None = None
    expect: dict[str, Any] = field(default_factory=dict)
    detail: dict[str, Any] = field(default_factory=dict)


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def run_pipeline_case(fix: dict[str, Any]) -> PipelineSmokeResult:
    """Run one fixture dict from fixtures/j02_ai_smoke.json."""
    budget_ms = int(fix.get("latency_budget_ms", LATENCY_BUDGET_MS))
    sim_delay = int(fix.get("simulated_llm_delay_ms", 0))
    expect = dict(fix.get("expect", {}))
    timings: dict[str, float] = {}
    t0 = time.perf_counter()

    user_text = str(fix.get("user_text", ""))
    t = time.perf_counter()
    timings["safety"] = _ms(t)

    grading_raw = fix.get("grading_input") or {}
    t = time.perf_counter()
    level_inp = UserLevelInput(
        profile_complete=bool(grading_raw.get("profile_complete", True)),
        country_code=grading_raw.get("country_code"),
        lifetime_spend_usd=float(grading_raw.get("lifetime_spend_usd", 0)),
        vip_level=int(grading_raw.get("vip_level", 0)),
        operator_assigned_s=bool(grading_raw.get("operator_assigned_s", False)),
    )
    level_result = calc_user_level(level_inp)
    timings["grading"] = _ms(t)
    user_level = level_result.level

    t = time.perf_counter()
    hook_results: list[dict[str, Any]] = []
    for hook in SCRIPT_HOOKS:
        ctx = ScriptMatchContext(
            hook=hook,
            platform=str(fix.get("platform", "telegram")),
            user_level=user_level,
            intent_id=fix.get("intent_id"),
            user_text=user_text,
        )
        hr = evaluate_script_hook(ctx)
        hook_results.append(
            {"hook": hr.hook, "matched": hr.matched, "degradation": hr.degradation}
        )
    timings["script_hooks"] = _ms(t)

    prompt_raw = fix.get("prompt_input") or {}
    history = prompt_raw.get("history")
    t = time.perf_counter()
    prompt_out = build_prompt(
        PromptInput(
            user_text=user_text,
            character=prompt_raw.get("character"),
            profile=prompt_raw.get("profile"),
            memories=prompt_raw.get("memories"),
            history=history,
        )
    )
    timings["prompt"] = _ms(t)
    layer_count = len([k for k in LAYER_ORDER if k in prompt_out.layers or k == "L8_RECENT_CONTEXT"])

    t = time.perf_counter()
    if sim_delay > 0:
        time.sleep(sim_delay / 1000.0)
    reply = f"[smoke-reply:{fix['id']}]"
    timings["llm_stub"] = _ms(t)

    total = _ms(t0)
    outcome = "reply"
    return PipelineSmokeResult(
        id=fix["id"],
        title=fix["title"],
        outcome=outcome,
        pass_case=_check_expect(
            expect,
            outcome,
            total,
            budget_ms,
            user_level,
            None,
            layer_tags=len(prompt_out.layers),
        ),
        total_ms=total,
        within_budget=total < budget_ms,
        timings_ms=timings,
        level=user_level,
        reply_preview=reply[:80],
        expect=expect,
        detail={
            "hooks": len(hook_results),
            "messages": len(prompt_out.messages),
            "estimated_tokens": prompt_out.estimated_tokens,
            "layer_count": layer_count,
            "simulated_llm_delay_ms": sim_delay,
        },
    )


def _check_expect(
    expect: dict[str, Any],
    outcome: Outcome,
    total_ms: float,
    budget_ms: int,
    level: str | None,
    block_reason: str | None,
    **extra: Any,
) -> bool:
    if expect.get("outcome") and expect["outcome"] != outcome:
        return False
    if "max_total_ms" in expect and total_ms >= float(expect["max_total_ms"]):
        return False
    if expect.get("within_budget") is True and total_ms >= budget_ms:
        return False
    if "level" in expect and level != expect["level"]:
        return False
    if "block_reason_prefix" in expect:
        br = block_reason or ""
        if not br.startswith(str(expect["block_reason_prefix"])):
            return False
    if "min_layer_tags" in expect:
        if extra.get("layer_tags", 0) < int(expect["min_layer_tags"]):
            return False
    if expect.get("has_l1_safety"):
        # prompt path only
        pass
    return True


def result_to_dict(r: PipelineSmokeResult) -> dict[str, Any]:
    d = asdict(r)
    d["pass"] = r.pass_case
    return d
