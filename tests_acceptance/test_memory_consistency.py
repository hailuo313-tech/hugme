"""D4-2 任务卡 9：``memory_consistency`` 规则过滤单测。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.memory_consistency import filter_memory_hits_for_current_utterance


def _hit(content: str, mid: str = "m1") -> SimpleNamespace:
    return SimpleNamespace(
        id=mid,
        content=content,
        memory_type="fact",
        importance_score=7.0,
        confidence_score=1.0,
        emotion_tags=[],
        created_at=None,
        last_used_at=None,
        similarity=0.5,
        final_score=0.5,
    )


def test_keeps_hits_when_no_signal():
    hits = [_hit("用户喜欢爵士乐"), _hit("用户住上海")]
    kept, dropped = filter_memory_hits_for_current_utterance("今天天气不错", hits)
    assert dropped == 0
    assert len(kept) == 2


def test_drops_partner_memory_when_user_says_broke_up():
    hits = [_hit("用户和男朋友感情稳定，经常一起旅游"), _hit("用户养了一只猫叫年糕")]
    kept, dropped = filter_memory_hits_for_current_utterance("我们分手了，别跟我提他", hits)
    assert dropped == 1
    assert len(kept) == 1
    assert "猫" in kept[0].content


def test_drops_married_memory_when_user_says_single():
    hits = [_hit("用户去年领证结婚，配偶在银行工作")]
    kept, dropped = filter_memory_hits_for_current_utterance("我单身了，想重新开始", hits)
    assert dropped == 1
    assert kept == []


@pytest.mark.parametrize(
    "user,mem,expect_drop",
    [
        ("我现在不吃辣了", "用户最爱吃辣，无辣不欢", True),
        ("我特别爱吃辣", "用户不吃辣，完全忌口", True),
        ("我喜欢微辣", "用户爱吃川菜", False),
    ],
)
def test_spicy_flip(user: str, mem: str, expect_drop: bool):
    hits = [_hit(mem)]
    kept, dropped = filter_memory_hits_for_current_utterance(user, hits)
    assert (dropped == 1) is expect_drop
    assert (len(kept) == 0) is expect_drop


def test_empty_hits():
    kept, dropped = filter_memory_hits_for_current_utterance("我们分手了", [])
    assert kept == [] and dropped == 0


def test_empty_user_text_keeps_all():
    hits = [_hit("用户有女朋友")]
    kept, dropped = filter_memory_hits_for_current_utterance("   ", hits)
    assert dropped == 0
    assert len(kept) == 1


def test_skips_empty_memory_content():
    hits = [_hit(""), _hit("用户喜欢跑步")]
    kept, dropped = filter_memory_hits_for_current_utterance("我们分手了", hits)
    assert dropped == 0
    assert len(kept) == 2
