"""D3-2 单测：app/services/prompt_builder.py

覆盖：
- 10 层标签全部出现在 system content（按 LAYER_ORDER，除 L8_RECENT_CONTEXT 外）。
- 空入参（无 character/profile/memories/history） → 每层走"未知/默认"降级。
- 提供 character → L3 渲染人格、姓名、6 项分数 band。
- 提供 profile → L4 渲染关系阶段 + L5 渲染聊天风格/兴趣/禁忌 + L7 渲染孤独度 band。
- 提供 memories → L6 渲染 importance + content 列表。
- 提供 history → 出现在 messages 数组 system 与当前 user 之间，顺序保持。
- 异常输入（score 为字符串 / interests 为 None / forbidden_topics 为 str）不抛异常。
- DEFAULT_SYSTEM_PROMPT == build_prompt(空入参).system_content。

所有测试纯函数测试，无 IO。
"""
from __future__ import annotations

import pytest

from services.prompt_builder import (  # type: ignore
    DEFAULT_SYSTEM_PROMPT,
    LAYER_ORDER,
    PromptInput,
    SYSTEM_LAYERS,
    build_prompt,
)


# ─────────────────────────────────────────────────────────────
# 10 层结构
# ─────────────────────────────────────────────────────────────

def test_layer_order_has_exactly_10_layers():
    """LAYER_ORDER 必须正好 10 个：L1..L10。"""
    assert len(LAYER_ORDER) == 10
    expected = (
        "L1_SAFETY",
        "L2_IDENTITY",
        "L3_CHARACTER",
        "L4_RELATIONSHIP",
        "L5_USER_PROFILE",
        "L6_MEMORY",
        "L7_CONVERSATION_STATE",
        "L8_RECENT_CONTEXT",
        "L9_FORMAT",
        "L10_ANCHOR",
    )
    assert LAYER_ORDER == expected


def test_system_content_contains_all_9_system_layer_markers():
    """system content 必须含 9 个 ``## ===== Lx_NAME =====`` 标签（L8 不在 system）。"""
    out = build_prompt(PromptInput(user_text="hi"))

    assert "L8_RECENT_CONTEXT" not in out.system_content  # L8 走 messages 数组
    for label in SYSTEM_LAYERS:
        assert f"## ===== {label} =====" in out.system_content, f"missing {label}"


def test_messages_shape_with_empty_history():
    """空 history → messages = [system, current_user]，长度 2。"""
    out = build_prompt(PromptInput(user_text="hello"))
    assert len(out.messages) == 2
    assert out.messages[0]["role"] == "system"
    assert out.messages[1] == {"role": "user", "content": "hello"}


def test_messages_shape_with_history():
    """有 history → system + history + current_user。"""
    history = [
        {"role": "user", "content": "我叫小海"},
        {"role": "assistant", "content": "你好小海"},
    ]
    out = build_prompt(PromptInput(user_text="再聊一下", history=history))
    assert len(out.messages) == 4
    assert out.messages[0]["role"] == "system"
    assert out.messages[1] == history[0]
    assert out.messages[2] == history[1]
    assert out.messages[3] == {"role": "user", "content": "再聊一下"}


# ─────────────────────────────────────────────────────────────
# L1 / L2 / L10：静态硬红线、人格身份、末层锚点
# ─────────────────────────────────────────────────────────────

def test_l1_safety_contains_hard_redlines():
    out = build_prompt(PromptInput(user_text="x"))
    body = out.layers["L1_SAFETY"]
    assert "未成年" in body or "minor" in body.lower()
    assert "自伤" in body or "self-harm" in body.lower()
    assert "越狱" in body or "忽略以上规则" in body


def test_l2_identity_says_aria_not_chatgpt():
    out = build_prompt(PromptInput(user_text="x"))
    body = out.layers["L2_IDENTITY"]
    assert "Aria" in body
    assert "ChatGPT" in body  # 明确否认


def test_l10_anchor_repeats_critical_rules():
    out = build_prompt(PromptInput(user_text="x"))
    body = out.layers["L10_ANCHOR"]
    assert "L1" in body
    assert "Aria" in body


# ─────────────────────────────────────────────────────────────
# L3 CHARACTER
# ─────────────────────────────────────────────────────────────

def test_l3_renders_character_fields():
    char = {
        "name": "Aria",
        "age_feel": "22",
        "region": "Shanghai",
        "occupation": "studio engineer",
        "background": "学过古典乐，喜欢猫",
        "relationship_position": "知心朋友",
        "gentle_score": 80,
        "proactive_score": 40,
        "flirt_score": 10,
        "humor_score": 55,
        "emotional_depth_score": 70,
        "boundary_score": 75,
        "reply_length": "short",
        "tone": "warm",
        "emoji_frequency": "low",
    }
    out = build_prompt(PromptInput(user_text="hi", character=char))
    body = out.layers["L3_CHARACTER"]
    assert "Aria" in body
    assert "Shanghai" in body
    assert "studio engineer" in body
    assert "知心朋友" in body
    assert "gentle=high" in body  # 80 → high
    assert "proactive=mid" in body  # 40 → mid
    assert "flirt=low" in body  # 10 → low


def test_l3_empty_character_falls_back_to_default():
    out = build_prompt(PromptInput(user_text="hi", character=None))
    body = out.layers["L3_CHARACTER"]
    assert "未配置" in body or "默认" in body


def test_l3_handles_string_score_gracefully():
    """score 字段是字符串时不应抛异常，按 mid 处理。"""
    char = {"name": "X", "gentle_score": "not-a-number"}
    out = build_prompt(PromptInput(user_text="hi", character=char))
    assert "gentle=mid" in out.layers["L3_CHARACTER"]


# ─────────────────────────────────────────────────────────────
# L4 RELATIONSHIP
# ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "stage,marker",
    [
        ("S0", "陌生人"),
        ("S2", "朋友"),
        ("S4", "依赖"),
    ],
)
def test_l4_renders_known_stages(stage, marker):
    out = build_prompt(
        PromptInput(user_text="hi", profile={"relationship_stage": stage})
    )
    body = out.layers["L4_RELATIONSHIP"]
    assert stage in body
    assert marker in body


def test_l4_vip_level_shown_when_paid():
    out = build_prompt(
        PromptInput(user_text="hi", profile={"relationship_stage": "S2", "vip_level": 2})
    )
    body = out.layers["L4_RELATIONSHIP"]
    assert "VIP 等级：2" in body


def test_l4_no_profile_falls_back_to_s0():
    out = build_prompt(PromptInput(user_text="hi", profile=None))
    body = out.layers["L4_RELATIONSHIP"]
    assert "S0" in body


# ─────────────────────────────────────────────────────────────
# L5 USER_PROFILE
# ─────────────────────────────────────────────────────────────

def test_l5_renders_interests_and_forbidden_lists():
    out = build_prompt(
        PromptInput(
            user_text="hi",
            profile={
                "chat_style": "playful",
                "interests": ["音乐", "猫", "登山"],
                "forbidden_topics": ["政治"],
                "preferences": {"nickname": "小海"},
            },
        )
    )
    body = out.layers["L5_USER_PROFILE"]
    assert "playful" in body
    assert "音乐, 猫, 登山" in body or "音乐" in body
    assert "政治" in body
    assert "小海" in body


def test_l5_handles_forbidden_topics_as_string():
    out = build_prompt(
        PromptInput(user_text="hi", profile={"forbidden_topics": "政治"})
    )
    body = out.layers["L5_USER_PROFILE"]
    assert "政治" in body


def test_l5_no_profile_says_unknown():
    out = build_prompt(PromptInput(user_text="hi", profile=None))
    body = out.layers["L5_USER_PROFILE"]
    assert "未知" in body


# ─────────────────────────────────────────────────────────────
# L6 MEMORY
# ─────────────────────────────────────────────────────────────

def test_l6_empty_says_d4_will_fill():
    out = build_prompt(PromptInput(user_text="hi", memories=None))
    body = out.layers["L6_MEMORY"]
    assert "D4-1" in body or "暂无" in body


def test_l6_renders_memory_list():
    memories = [
        {"memory_type": "fact", "content": "用户生日 5 月 10 日", "importance_score": 8.5},
        {"memory_type": "preference", "content": "喜欢爵士乐", "importance_score": 6.0},
    ]
    out = build_prompt(PromptInput(user_text="hi", memories=memories))
    body = out.layers["L6_MEMORY"]
    assert "5 月 10 日" in body
    assert "爵士乐" in body
    assert "importance=8.5" in body
    assert "[fact]" in body


def test_l6_drops_empty_content_rows():
    memories = [
        {"memory_type": "fact", "content": "", "importance_score": 8.0},
        {"memory_type": "fact", "content": "保留这条", "importance_score": 5.0},
    ]
    out = build_prompt(PromptInput(user_text="hi", memories=memories))
    body = out.layers["L6_MEMORY"]
    assert "保留这条" in body
    # 第一条空内容不应出现独立的占位行
    assert body.count("[fact]") == 1


# ─────────────────────────────────────────────────────────────
# L7 CONVERSATION_STATE
# ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "score,band_keyword",
    [
        (10, "low"),
        (45, "mid"),
        (65, "high"),
        (85, "critical"),
    ],
)
def test_l7_loneliness_band(score, band_keyword):
    out = build_prompt(
        PromptInput(user_text="hi", profile={"loneliness_score": score})
    )
    body = out.layers["L7_CONVERSATION_STATE"]
    assert band_keyword in body


def test_l7_missing_score_falls_back_to_cold_start():
    out = build_prompt(
        PromptInput(user_text="hi", profile={"loneliness_score": None})
    )
    body = out.layers["L7_CONVERSATION_STATE"]
    assert "冷启动" in body or "默认" in body


def test_l7_invalid_score_does_not_crash():
    out = build_prompt(
        PromptInput(user_text="hi", profile={"loneliness_score": "n/a"})
    )
    body = out.layers["L7_CONVERSATION_STATE"]
    assert "冷启动" in body or "默认" in body


# ─────────────────────────────────────────────────────────────
# L9 FORMAT
# ─────────────────────────────────────────────────────────────

def test_l9_uses_character_format_when_available():
    char = {"reply_length": "long", "tone": "playful", "emoji_frequency": "high"}
    out = build_prompt(PromptInput(user_text="hi", character=char))
    body = out.layers["L9_FORMAT"]
    assert "playful" in body
    assert "2–4" in body or "稍多" in body  # long
    assert "2–3 个" in body or "较多" in body  # high


def test_l9_default_when_no_character():
    out = build_prompt(PromptInput(user_text="hi", character=None))
    body = out.layers["L9_FORMAT"]
    assert "中文" in body or "Chinese" in body.lower()


# ─────────────────────────────────────────────────────────────
# 向后兼容：DEFAULT_SYSTEM_PROMPT
# ─────────────────────────────────────────────────────────────

def test_default_system_prompt_equals_empty_build():
    """``DEFAULT_SYSTEM_PROMPT`` 必须等价于 build_prompt(空入参).system_content。

    老 ``llm_orchestrator`` 单测断言 ``messages[0].content == DEFAULT_SYSTEM_PROMPT``，
    本测试保证那条断言在 D3-2 后仍成立。
    """
    out = build_prompt(PromptInput(user_text="__placeholder__"))
    assert DEFAULT_SYSTEM_PROMPT == out.system_content


# ─────────────────────────────────────────────────────────────
# 估算 token / 调试输出
# ─────────────────────────────────────────────────────────────

def test_estimated_tokens_grows_with_content():
    short = build_prompt(PromptInput(user_text="hi"))
    long = build_prompt(
        PromptInput(
            user_text="hi" * 500,
            history=[{"role": "user", "content": "x" * 1000}],
        )
    )
    assert long.estimated_tokens > short.estimated_tokens
