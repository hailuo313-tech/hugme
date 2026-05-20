"""D3-3 单元测试：app/services/memory_writer.py

覆盖三个 phase：
- Phase 1 规则预过滤：too_short / acknowledgement / emoji_only / duplicate
- Phase 2 LLM 评分：happy / 模型 5xx / JSON 解析错 / 类型白名单 / 阈值
- Phase 3 持久化：成功插入 + memory_id 返回 + DB error 降级

所有 LLM / DB / Redis 通过 monkeypatch 注入 stub，纯本地、零外部依赖。
"""

from __future__ import annotations

import importlib
import json

import pytest


# ─────────────────────────────────────────────────────────────
# fixtures
# ─────────────────────────────────────────────────────────────


@pytest.fixture
def mw():
    """每个测试都 reload，避免 monkeypatch 污染。"""
    import services.memory_writer as mod  # type: ignore

    importlib.reload(mod)
    return mod


class _FakeRedis:
    """实现 sadd / expire / 抛异常切换。"""

    def __init__(self):
        self.sets: dict[str, set[str]] = {}
        self.fail_on_sadd: bool = False

    async def sadd(self, key: str, *values: str) -> int:
        if self.fail_on_sadd:
            raise RuntimeError("redis down")
        s = self.sets.setdefault(key, set())
        added = 0
        for v in values:
            if v not in s:
                s.add(v)
                added += 1
        return added

    async def expire(self, key: str, ttl: int) -> bool:
        return True


class _CapturingDB:
    """记录所有 execute 参数；commit 计数。"""

    def __init__(self, fail: bool = False):
        self.calls: list[tuple[str, dict]] = []
        self.commits: int = 0
        self.fail = fail

    async def execute(self, stmt, params=None):
        if self.fail:
            raise RuntimeError("db dead")
        sql = str(getattr(stmt, "text", stmt))
        self.calls.append((sql, params or {}))
        return _DummyResult()

    async def commit(self):
        if self.fail:
            raise RuntimeError("db dead on commit")
        self.commits += 1


class _DummyResult:
    def fetchone(self):
        return None


class _LLMStub:
    """模拟 services.llm.LLMResult。"""

    def __init__(
        self,
        content: str = "",
        error: str | None = None,
        model_used: str = "openai/gpt-4o-mini",
    ):
        self.content = content
        self.error = error
        self.model_used = model_used
        self.usage = {"prompt_tokens": 50, "completion_tokens": 30}
        self.latency_ms = 100.0
        self.fallback_used = False


def _valid_eval_json(
    is_worthy: bool = True,
    score: int = 7,
    mtype: str = "preference",
) -> str:
    return json.dumps(
        {
            "is_memory_worthy": is_worthy,
            "memory_type": mtype,
            "content": "用户喜欢爵士乐",
            "importance_score": score,
            "confidence": 0.9,
            "emotion_tags": ["calm"],
        },
        ensure_ascii=False,
    )


# ─────────────────────────────────────────────────────────────
# Phase 1: 规则预过滤
# ─────────────────────────────────────────────────────────────


class TestPrefilter:
    @pytest.mark.parametrize(
        "content,expected_reason",
        [
            ("", "empty"),
            ("   ", "empty"),
            ("嗯", "too_short"),
            ("ok", "acknowledgement"),
            ("好的", "acknowledgement"),
            ("Thanks!", "acknowledgement"),
            ("😊😀🎉", "emoji_or_punct_only"),
            ("。。。？？？", "emoji_or_punct_only"),
            ("我今天买了一台新相机感觉很满足", None),  # 正常通过
        ],
    )
    def test_rule_prefilter_cases(self, mw, content, expected_reason):
        result = mw._rule_prefilter(content)
        assert result == expected_reason


# ─────────────────────────────────────────────────────────────
# Phase 2: LLM 解析
# ─────────────────────────────────────────────────────────────


class TestParseEvaluation:
    def test_plain_json(self, mw):
        obj = mw._parse_evaluation(_valid_eval_json())
        assert obj is not None
        assert obj["is_memory_worthy"] is True
        assert obj["memory_type"] == "preference"
        assert obj["importance_score"] == 7
        assert obj["emotion_tags"] == ["calm"]

    def test_markdown_fenced_json(self, mw):
        raw = "```json\n" + _valid_eval_json() + "\n```"
        obj = mw._parse_evaluation(raw)
        assert obj is not None
        assert obj["memory_type"] == "preference"

    def test_prefix_explanation_then_json(self, mw):
        raw = "好的，分析结果如下：\n" + _valid_eval_json() + "\n谢谢"
        obj = mw._parse_evaluation(raw)
        assert obj is not None

    def test_invalid_json_returns_none(self, mw):
        assert mw._parse_evaluation("not json at all") is None
        assert mw._parse_evaluation("") is None
        assert mw._parse_evaluation("{") is None

    def test_empty_content_field_returns_none(self, mw):
        raw = json.dumps(
            {
                "is_memory_worthy": True,
                "memory_type": "fact",
                "content": "",
                "importance_score": 8,
            }
        )
        assert mw._parse_evaluation(raw) is None

    def test_invalid_score_coerced_to_zero(self, mw):
        raw = json.dumps(
            {
                "is_memory_worthy": True,
                "memory_type": "fact",
                "content": "x",
                "importance_score": "not a number",
            }
        )
        obj = mw._parse_evaluation(raw)
        assert obj is not None
        assert obj["importance_score"] == 0


# ─────────────────────────────────────────────────────────────
# 端到端：maybe_write_memory
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_persists_memory(mw, monkeypatch):
    async def fake_llm(*, messages, trace_id, **_kwargs):
        return _LLMStub(content=_valid_eval_json(score=8))

    monkeypatch.setattr(mw, "llm_chat", fake_llm)
    monkeypatch.setattr(mw.settings, "MEMORY_WRITE_ENABLED", True)
    monkeypatch.setattr(mw.settings, "MEMORY_IMPORTANCE_THRESHOLD", 5)

    db = _CapturingDB()
    redis = _FakeRedis()

    memory_id = await mw.maybe_write_memory(
        user_id="u1",
        conversation_id="c1",
        message_id="m1",
        content="我从小在上海长大，家里有一只叫橘子的猫",
        trace_id="t1",
        redis=redis,
        db=db,
    )

    assert memory_id is not None
    assert db.commits == 1
    assert len(db.calls) == 1
    sql, params = db.calls[0]
    assert "INSERT INTO memories" in sql
    assert params["uid"] == "u1"
    assert params["src"] == "m1"
    assert params["mt"] == "preference"
    assert params["imp"] == 8.0


@pytest.mark.asyncio
async def test_disabled_flag_short_circuits(mw, monkeypatch):
    """MEMORY_WRITE_ENABLED=False 应立刻 noop。"""
    monkeypatch.setattr(mw.settings, "MEMORY_WRITE_ENABLED", False)

    async def explode(*_a, **_k):
        raise AssertionError("llm should not be called when disabled")

    monkeypatch.setattr(mw, "llm_chat", explode)

    result = await mw.maybe_write_memory(
        user_id="u",
        conversation_id="c",
        message_id="m",
        content="正常长度的一句话试试",
        trace_id="t",
        db=_CapturingDB(),
    )
    assert result is None


@pytest.mark.asyncio
async def test_onboarding_skip(mw, monkeypatch):
    async def explode(*_a, **_k):
        raise AssertionError("llm should not be called during onboarding")

    monkeypatch.setattr(mw, "llm_chat", explode)
    monkeypatch.setattr(mw.settings, "MEMORY_WRITE_ENABLED", True)

    result = await mw.maybe_write_memory(
        user_id="u",
        conversation_id="c",
        message_id="m",
        content="我叫小海，今年 25 岁",
        trace_id="t",
        is_onboarding=True,
        db=_CapturingDB(),
    )
    assert result is None


@pytest.mark.asyncio
async def test_below_threshold_does_not_persist(mw, monkeypatch):
    async def low_score_llm(*, messages, trace_id, **_kwargs):
        return _LLMStub(content=_valid_eval_json(score=3))

    monkeypatch.setattr(mw, "llm_chat", low_score_llm)
    monkeypatch.setattr(mw.settings, "MEMORY_WRITE_ENABLED", True)
    monkeypatch.setattr(mw.settings, "MEMORY_IMPORTANCE_THRESHOLD", 5)

    db = _CapturingDB()

    result = await mw.maybe_write_memory(
        user_id="u",
        conversation_id="c",
        message_id="m",
        content="今天天气不错的样子吧",
        trace_id="t",
        db=db,
    )
    assert result is None
    assert db.commits == 0


@pytest.mark.asyncio
async def test_llm_error_skips_gracefully(mw, monkeypatch):
    async def bad_llm(*, messages, trace_id, **_kwargs):
        return _LLMStub(content="", error="primary=timeout; fallback=5xx")

    monkeypatch.setattr(mw, "llm_chat", bad_llm)
    monkeypatch.setattr(mw.settings, "MEMORY_WRITE_ENABLED", True)

    db = _CapturingDB()
    result = await mw.maybe_write_memory(
        user_id="u",
        conversation_id="c",
        message_id="m",
        content="正常长度的一句话",
        trace_id="t",
        db=db,
    )
    assert result is None
    assert db.commits == 0


@pytest.mark.asyncio
async def test_llm_exception_does_not_propagate(mw, monkeypatch):
    async def kaboom(*_a, **_k):
        raise TimeoutError("upstream timeout")

    monkeypatch.setattr(mw, "llm_chat", kaboom)
    monkeypatch.setattr(mw.settings, "MEMORY_WRITE_ENABLED", True)

    result = await mw.maybe_write_memory(
        user_id="u",
        conversation_id="c",
        message_id="m",
        content="正常长度的一句话",
        trace_id="t",
        db=_CapturingDB(),
    )
    assert result is None


@pytest.mark.asyncio
async def test_invalid_memory_type_falls_back_to_fact(mw, monkeypatch):
    """LLM 返回的 memory_type 不在白名单 → 降级为 fact 但仍可保存。"""
    raw = json.dumps(
        {
            "is_memory_worthy": True,
            "memory_type": "weird_unknown_type",
            "content": "用户偏爱深夜聊天",
            "importance_score": 7,
            "confidence": 0.8,
            "emotion_tags": [],
        }
    )

    async def fake_llm(*, messages, trace_id, **_kwargs):
        return _LLMStub(content=raw)

    monkeypatch.setattr(mw, "llm_chat", fake_llm)
    monkeypatch.setattr(mw.settings, "MEMORY_WRITE_ENABLED", True)
    monkeypatch.setattr(mw.settings, "MEMORY_IMPORTANCE_THRESHOLD", 5)

    db = _CapturingDB()
    result = await mw.maybe_write_memory(
        user_id="u",
        conversation_id="c",
        message_id="m",
        content="我有时候喜欢深夜跟人聊聊心里话",
        trace_id="t",
        db=db,
    )
    assert result is not None
    _, params = db.calls[0]
    assert params["mt"] == "fact"  # 白名单降级


@pytest.mark.asyncio
async def test_duplicate_within_24h_skipped(mw, monkeypatch):
    """24h 内同一用户重复内容 → Phase 1 跳过，不进 LLM。"""

    async def explode(*_a, **_k):
        raise AssertionError("llm should not be called on duplicate")

    monkeypatch.setattr(mw, "llm_chat", explode)
    monkeypatch.setattr(mw.settings, "MEMORY_WRITE_ENABLED", True)

    redis = _FakeRedis()
    # 预先把内容 hash 塞进去
    h = mw._content_hash("我每天都会做瑜伽放松一下")
    redis.sets["dedup:mem:u1"] = {h}

    result = await mw.maybe_write_memory(
        user_id="u1",
        conversation_id="c",
        message_id="m",
        content="我每天都会做瑜伽放松一下",
        trace_id="t",
        redis=redis,
        db=_CapturingDB(),
    )
    assert result is None


@pytest.mark.asyncio
async def test_redis_failure_does_not_block(mw, monkeypatch):
    """Redis sadd 抛异常 → 视为未重复，继续往下走。"""

    async def fake_llm(*, messages, trace_id, **_kwargs):
        return _LLMStub(content=_valid_eval_json(score=8))

    monkeypatch.setattr(mw, "llm_chat", fake_llm)
    monkeypatch.setattr(mw.settings, "MEMORY_WRITE_ENABLED", True)
    monkeypatch.setattr(mw.settings, "MEMORY_IMPORTANCE_THRESHOLD", 5)

    redis = _FakeRedis()
    redis.fail_on_sadd = True

    db = _CapturingDB()
    result = await mw.maybe_write_memory(
        user_id="u",
        conversation_id="c",
        message_id="m",
        content="我从小在上海长大",
        trace_id="t",
        redis=redis,
        db=db,
    )
    assert result is not None
    assert db.commits == 1


@pytest.mark.asyncio
async def test_db_failure_returns_none_not_raise(mw, monkeypatch):
    async def fake_llm(*, messages, trace_id, **_kwargs):
        return _LLMStub(content=_valid_eval_json(score=8))

    monkeypatch.setattr(mw, "llm_chat", fake_llm)
    monkeypatch.setattr(mw.settings, "MEMORY_WRITE_ENABLED", True)

    db = _CapturingDB(fail=True)

    # 不应抛异常
    result = await mw.maybe_write_memory(
        user_id="u",
        conversation_id="c",
        message_id="m",
        content="我从小在上海长大",
        trace_id="t",
        db=db,
    )
    assert result is None
