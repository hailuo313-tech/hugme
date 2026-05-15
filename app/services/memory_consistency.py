"""D4-2 任务卡 9：检索记忆与「当前用户句」的一致性过滤（可选、轻量）。

产品定义（一句）
===============
**长期记忆**描述的是历史上写入的、相对稳定的用户事实；**冲突**指用户**当前这句**
在同一主题上给出与该记忆**互斥的现况陈述**（例如记忆仍写「与恋人稳定交往」，
用户本句说「我们昨天分手了」）。冲突时该条记忆**本轮不注入 L6**，避免模型把
过期事实当成现在时断言。

实现策略
========
- **默认**：仅关键字 / 正则规则，**不调 LLM**，额外 completion 成本为 **0**。
- ``MEMORY_CONSISTENCY_LLM_MAX_OUTPUT_TOKENS`` 预留为 **>0** 时未来可接轻量二次
  校验（本文件尚未接 LLM，仅占位配置以满足「成本上限」可述）。

规则（保守、宁可少过滤）
=======================
1. 用户自述**感情结束 / 恢复单身**等信号，且记忆正文仍含**伴侣 / 热恋 / 稳定交往**
   等亲密表述 → 丢弃该条。
2. 用户自述**单身 / 没对象**，且记忆正文含**已婚 / 领证 / 婚礼**等 → 丢弃。
3. **辣口味**：用户本句明确「不吃辣 / 忌辣」，记忆写「爱吃辣 / 无辣不欢」→ 丢弃；
   反向（用户爱吃辣、记忆忌辣）同理。

以上规则均只作用于**本轮**注入列表，不写回数据库。
"""
from __future__ import annotations

import re
from typing import Any, Sequence, TypeVar

T = TypeVar("T")

# 用户：感情结束 / 否定当前亲密关系（尽量收窄，减少「朋友分手」误伤）
_USER_REL_END_RE = re.compile(
    r"(我们分手了|我分手了|和他分手了|和她分手了|跟男友分手|跟女友分手|"
    r"离婚了|我离婚了|离过婚了|掰了|散伙了|结束这段感情|不爱了|出轨了|"
    r"we broke up|i broke up|getting divorced|i'?m divorced)",
    re.IGNORECASE | re.UNICODE,
)

_USER_SINGLE_NOW_RE = re.compile(
    r"(我单身|单身了|现在单身|现在一个人|没对象|没有男朋友|没有女朋友|"
    r"i\s*'?m\s*single|no\s+boyfriend|no\s+girlfriend)",
    re.IGNORECASE | re.UNICODE,
)

# 记忆：仍描述亲密伴侣 / 稳定交往
_MEMORY_PARTNER_RE = re.compile(
    r"(女(朋)?友|男(朋)?友|男朋友|女朋友|恋人|对象|老公|老婆|丈夫|妻子|"
    r"未婚夫|未婚妻|谈恋爱|交往中|热恋|恩爱|稳定交往|另一半|"
    r"boyfriend|girlfriend|partner|dating|married to|spouse|fiance)",
    re.IGNORECASE | re.UNICODE,
)

_MEMORY_MARRIED_RE = re.compile(
    r"(已婚|结婚|领证|婚礼|marriage|married|wife|husband)",
    re.IGNORECASE | re.UNICODE,
)

_SPICY_LIKE_MEM = re.compile(r"(爱吃辣|无辣不欢|最喜欢辣|顿顿要辣|离不了辣)", re.UNICODE)
_SPICY_HATE_USER = re.compile(r"(不吃辣|忌口辣|不能吃辣|忌辣|过敏.*辣)", re.UNICODE)
_SPICY_HATE_MEM = re.compile(r"(不吃辣|忌辣|不能吃辣|过敏.*辣)", re.UNICODE)
_SPICY_LIKE_USER = re.compile(r"(爱吃辣|特别爱吃辣|无辣不欢|顿顿要辣)", re.UNICODE)


def _mem_text(hit: Any) -> str:
    return (getattr(hit, "content", None) or "").strip()


def filter_memory_hits_for_current_utterance(
    user_text: str,
    hits: Sequence[T],
) -> tuple[list[T], int]:
    """按当前用户句过滤与记忆互斥的命中；保持原顺序。

    Returns:
        (kept_hits, dropped_count)
    """
    if not hits:
        return [], 0
    u = (user_text or "").strip()
    if not u:
        return list(hits), 0

    rel_end = bool(_USER_REL_END_RE.search(u))
    single_now = bool(_USER_SINGLE_NOW_RE.search(u))
    user_hate_spicy = bool(_SPICY_HATE_USER.search(u))
    user_like_spicy = bool(_SPICY_LIKE_USER.search(u))

    kept: list[T] = []
    dropped = 0

    for h in hits:
        mem = _mem_text(h)
        if not mem:
            kept.append(h)
            continue

        if rel_end and _MEMORY_PARTNER_RE.search(mem):
            dropped += 1
            continue

        if single_now and _MEMORY_MARRIED_RE.search(mem):
            dropped += 1
            continue

        if user_hate_spicy and _SPICY_LIKE_MEM.search(mem):
            dropped += 1
            continue

        if user_like_spicy and _SPICY_HATE_MEM.search(mem):
            dropped += 1
            continue

        kept.append(h)

    return kept, dropped
