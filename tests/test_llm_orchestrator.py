"""D2-2 / D2-2.1 单元测试：app/services/llm_orchestrator.py

覆盖：
- happy path：LLM 返回非空 content，orchestrator 透传。
- 上游异常 + 未启用 fallback → 抛 LLMOrchestratorError。
- LLMResult.error 非空 + 未启用 fallback → 抛 LLMOrchestratorError。
- LLM 返回空 content → 视为失败。
- 启用 LLM_ECHO_FALLBACK → 失败时回退为自然中文回复（非 echo 透传）。
- D2-2.1：传入 redis 客户端 → 历史消息被拼进 messages，角色映射正确，
  最末一条（=当前消息）被丢弃。
- D2-2.1：redis.lrange 抛异常 → 仍能完成调用，仅记录 warning。
- D2-2.1：history_limit=0 / redis=None → 不读取历史。
- D4-2：MEMORY_RETRIEVE_IN_PROMPT 开关 + mock retrieve → L6 含记忆正文；任务卡 9 一致性过滤。
- D4-3 / D4-4：refresh_loneliness_score 先于 memory_retrieve；无 profile 不调 refresh。

所有外部 IO（实际的 LLM HTTP 调用 + Redis）通过 monkeypatch / fake 对象拦截。
"""
from __future__ import annotations

import importlib
import json
from types import SimpleNamespace
from typing import Any

import pytest


# ── fixtures ───────────────────────────────────────────

@pytest.fixture
def llm_orchestrator():
    """每个测试都重新 import，避免 monkeypatch 残留。"""
    import services.llm_orchestrator as mod  # type: ignore

    importlib.reload(mod)
    return mod


class _FakeRedis:
    """轻量 redis 替身，只实现 orchestrator 用到的 lrange。"""

    def __init__(self, items: list[str] | Exception):
        self._items = items

    async def lrange(self, key: str, start: int, end: int):
        if isinstance(self._items, Exception):
            raise self._items
        # 模拟 Redis lrange(-N, -1) 行为：返回最后 |start| 条
        items = self._items
        if start < 0:
            start_idx = max(0, len(items) + start)
        else:
            start_idx = start
        if end < 0:
            end_idx = len(items) + end + 1
        else:
            end_idx = end + 1
        return items[start_idx:end_idx]


def _ctx_entry(role: str, content: str, msg_id: str = "m") -> str:
    return json.dumps(
        {"role": role, "content": content, "msg_id": msg_id, "ts": 1},
        ensure_ascii=False,
    )


class _LLMResultStub:
    """轻量替身，模拟 services.llm.LLMResult 的字段。"""

    def __init__(
        self,
        content: str = "",
        model_used: str = "test/model",
        usage: dict[str, Any] | None = None,
        latency_ms: float = 12.3,
        fallback_used: bool = False,
        error: str | None = None,
    ) -> None:
        self.content = content
        self.model_used = model_used
        self.usage = usage if usage is not None else {"prompt_tokens": 7, "completion_tokens": 9}
        self.latency_ms = latency_ms
        self.fallback_used = fallback_used
        self.error = error


# ── tests ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_happy_path_returns_llm_content(monkeypatch, llm_orchestrator):
    """LLM 返回非空 content → orchestrator 透传返回值；trace_id 透传到 chat()。"""
    captured: dict[str, Any] = {}

    async def fake_chat(*, messages, trace_id, **_kwargs):
        captured["messages"] = messages
        captured["trace_id"] = trace_id
        return _LLMResultStub(content="hello from llm")

    monkeypatch.setattr(llm_orchestrator, "llm_chat", fake_chat)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)

    reply = await llm_orchestrator.generate_reply(
        user_id="user-1",
        conversation_id="conv-1",
        user_text="hi",
        trace_id="trace-happy",
    )

    assert reply == "hello from llm"
    assert captured["trace_id"] == "trace-happy"
    assert captured["messages"][0]["role"] == "system"
    assert captured["messages"][-1] == {"role": "user", "content": "hi"}


@pytest.mark.asyncio
async def test_asset_keyword_decision_skips_llm_refusal(monkeypatch, llm_orchestrator):
    async def fake_decision(**_kwargs):
        return SimpleNamespace(
            intent="asset_keyword_request",
            category_key="app_download_first_push",
            scene_step="asset_keyword:photo,video",
            script_hit_id="hit-asset",
            language="fr",
            assets=[
                {"asset_type": "image", "asset_url": "https://cdn.example/photo.jpg"},
                {"asset_type": "video", "asset_url": "https://cdn.example/video.mp4"},
            ],
        )

    async def fail_chat(**_kwargs):
        raise AssertionError("asset keyword replies must not call LLM")

    monkeypatch.setattr(llm_orchestrator, "maybe_select_app_download_reply", fake_decision)
    monkeypatch.setattr(llm_orchestrator, "llm_chat", fail_chat)
    monkeypatch.setattr(llm_orchestrator.settings, "MEMORY_RETRIEVE_IN_PROMPT", False)
    monkeypatch.setattr(llm_orchestrator.settings, "POLICY_SERVICE_ENABLED", False)
    monkeypatch.setattr(llm_orchestrator.settings, "REL_STAGE_AUTO_ENABLED", False)

    reply = await llm_orchestrator.generate_reply(
        user_id="u1",
        conversation_id="c1",
        user_text="tu peux m’envoyer des photos et vidéos",
        trace_id="t-asset",
        db=None,
    )

    assert "photos" in reply
    assert "vidéo" in reply
    assert "ne peux pas" not in reply.lower()


@pytest.mark.asyncio
async def test_app_download_nudge_keeps_llm_answer_first(monkeypatch, llm_orchestrator):
    async def fake_chat(*, messages, trace_id, **_kwargs):
        return _LLMResultStub(
            content="Yes, I can slow down. What do you actually want to talk about?"
        )

    async def fake_download_decision(**_kwargs):
        return SimpleNamespace(
            content=(
                "did u get scared of a voluptuous woman? "
                "fix it right here: https://app.example/download"
            ),
            category_key="app_link_clicked_followup",
            scene_step="clicked_not_downloaded",
            script_hit_id="script-1",
        )

    monkeypatch.setattr(llm_orchestrator, "llm_chat", fake_chat)
    monkeypatch.setattr(llm_orchestrator, "maybe_select_app_download_reply", fake_download_decision)

    reply = await llm_orchestrator.generate_reply(
        user_id="user-1",
        conversation_id="conv-1",
        user_text="Can you have a serious conversation?",
        trace_id="trace-download-nudge",
    )

    assert reply.startswith("Yes, I can slow down.")
    assert "If you still want to continue somewhere more private" in reply
    assert "https://app.example/download" in reply
    assert "voluptuous woman" not in reply


@pytest.mark.asyncio
async def test_app_download_direct_cta_keeps_llm_answer_first(monkeypatch, llm_orchestrator):
    async def fake_chat(*, messages, trace_id, **_kwargs):
        return _LLMResultStub(content="Here is the simple answer first.")

    async def fake_download_decision(**_kwargs):
        return SimpleNamespace(
            content="Here is the private link: https://app.example/download",
            category_key="app_download_direct_cta",
            scene_step="pre_click",
            script_hit_id="script-2",
        )

    monkeypatch.setattr(llm_orchestrator, "llm_chat", fake_chat)
    monkeypatch.setattr(llm_orchestrator, "maybe_select_app_download_reply", fake_download_decision)

    reply = await llm_orchestrator.generate_reply(
        user_id="user-1",
        conversation_id="conv-1",
        user_text="send me the app link",
        trace_id="trace-direct-cta",
    )

    assert reply.startswith("Here is the simple answer first.")
    assert "Let's chat on my private app instead, way safer than here." in reply
    assert "(Enter code: c5a8we)" in reply
    assert "https://app.example/download" in reply


def test_app_download_nudge_uses_scene_specific_copy(llm_orchestrator):
    url = "https://app.example/download"

    direct = llm_orchestrator._conservative_download_nudge(
        SimpleNamespace(category_key="app_download_direct_cta", content=url)
    )
    warmup = llm_orchestrator._conservative_download_nudge(
        SimpleNamespace(category_key="app_download_after_warmup", content=url)
    )
    objection = llm_orchestrator._conservative_download_nudge(
        SimpleNamespace(category_key="app_download_objection", content=url)
    )

    assert direct == (
        "Let's chat on my private app instead, way safer than here. "
        f"Grab it real quick and text me: {url} (Enter code: c5a8we)"
    )
    assert warmup == (
        "Btw, my TG is lagging crazy right now and missing texts. Drop me a line "
        f"on my main app here, it's free and way faster: {url} (Use code: c5a8we)"
    )
    assert objection == (
        "I only text close friends on my private encrypted app because TG keeps "
        f"censoring our topics anyway. Takes like 15 seconds to set up, come over: {url}"
    )


def test_short_preference_reply_trims_interview_followup(llm_orchestrator):
    reply = llm_orchestrator._repair_short_preference_interview_followup(
        "Doggy",
        "That's a popular choice! It can be pretty intense and exciting. What do you like most about it?",
    )

    assert reply == "That's a popular choice! It can be pretty intense and exciting."
    assert "What do you like most about it" not in reply


def test_short_preference_repair_does_not_touch_normal_messages(llm_orchestrator):
    reply = llm_orchestrator._repair_short_preference_interview_followup(
        "Can you talk?",
        "Sure. What do you like most about it?",
    )

    assert reply == "Sure. What do you like most about it?"


@pytest.mark.asyncio
async def test_upstream_exception_without_fallback(monkeypatch, llm_orchestrator):
    """上游 chat() 抛异常 + 未启用 fallback → 抛 LLMOrchestratorError。"""

    async def boom(*, messages, trace_id, **_kwargs):
        raise TimeoutError("upstream timeout")

    monkeypatch.setattr(llm_orchestrator, "llm_chat", boom)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)

    with pytest.raises(llm_orchestrator.LLMOrchestratorError):
        await llm_orchestrator.generate_reply(
            user_id="u",
            conversation_id="c",
            user_text="hi",
            trace_id="trace-fail",
        )


@pytest.mark.asyncio
async def test_llm_result_error_without_fallback(monkeypatch, llm_orchestrator):
    """LLMResult.error 非空（llm.chat 内部兜底）→ orchestrator 视为失败。"""

    async def returns_error(*, messages, trace_id, **_kwargs):
        return _LLMResultStub(
            content="[兜底文案]",
            error="primary=timeout; fallback=5xx",
            fallback_used=True,
        )

    monkeypatch.setattr(llm_orchestrator, "llm_chat", returns_error)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)

    with pytest.raises(llm_orchestrator.LLMOrchestratorError):
        await llm_orchestrator.generate_reply(
            user_id="u",
            conversation_id="c",
            user_text="hello",
            trace_id="trace-err",
        )


@pytest.mark.asyncio
async def test_empty_content_without_fallback(monkeypatch, llm_orchestrator):
    """LLM 返回空 content → 视为失败。"""

    async def empty(*, messages, trace_id, **_kwargs):
        return _LLMResultStub(content="", error=None)

    monkeypatch.setattr(llm_orchestrator, "llm_chat", empty)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)

    with pytest.raises(llm_orchestrator.LLMOrchestratorError):
        await llm_orchestrator.generate_reply(
            user_id="u",
            conversation_id="c",
            user_text="ok",
            trace_id="trace-empty",
        )


@pytest.mark.asyncio
async def test_fallback_returns_echo_when_enabled(monkeypatch, llm_orchestrator):
    """启用 LLM_ECHO_FALLBACK → LLM 失败时回退为自然回复。"""

    async def boom(*, messages, trace_id, **_kwargs):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(llm_orchestrator, "llm_chat", boom)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", True)

    reply = await llm_orchestrator.generate_reply(
        user_id="u",
        conversation_id="c",
        user_text="ping",
        trace_id="trace-fallback",
    )

    assert isinstance(reply, str) and len(reply) > 0


@pytest.mark.asyncio
async def test_fallback_on_llm_result_error_when_enabled(monkeypatch, llm_orchestrator):
    """启用 LLM_ECHO_FALLBACK + LLMResult.error 非空 → 也走自然回复兜底。"""

    async def with_error(*, messages, trace_id, **_kwargs):
        return _LLMResultStub(content="ignored", error="upstream timeout")

    monkeypatch.setattr(llm_orchestrator, "llm_chat", with_error)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", True)

    reply = await llm_orchestrator.generate_reply(
        user_id="u",
        conversation_id="c",
        user_text="pong",
        trace_id="trace-fallback-2",
    )

    assert isinstance(reply, str) and len(reply) > 0


# ── D2-2.1：Redis 短期上下文 ─────────────────────────────

@pytest.mark.asyncio
async def test_history_from_redis_is_inserted_between_system_and_user(
    monkeypatch, llm_orchestrator
):
    """传入 redis 时：ctx 里的历史被拼进 messages，最末一条丢弃，角色映射正确。"""
    captured: dict[str, Any] = {}

    async def fake_chat(*, messages, trace_id, **_kwargs):
        captured["messages"] = messages
        return _LLMResultStub(content="ok")

    monkeypatch.setattr(llm_orchestrator, "llm_chat", fake_chat)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)

    # ctx 中 4 条：3 条真历史 + 最末一条 = 当前用户消息（应被丢弃）
    redis = _FakeRedis(
        [
            _ctx_entry("user", "我叫小海"),
            _ctx_entry("assistant", "你好小海"),
            _ctx_entry("bot", "今天怎么样？"),   # 'bot' 应映射为 'assistant'
            _ctx_entry("user", "我今天有点累"),  # 最末一条 = 当前消息
        ]
    )

    reply = await llm_orchestrator.generate_reply(
        user_id="u",
        conversation_id="c",
        user_text="我今天有点累",
        trace_id="trace-ctx",
        redis=redis,
    )

    assert reply == "ok"
    msgs = captured["messages"]
    assert msgs[0]["role"] == "system"
    assert msgs[-1] == {"role": "user", "content": "我今天有点累"}
    history = msgs[1:-1]
    assert history == [
        {"role": "user", "content": "我叫小海"},
        {"role": "assistant", "content": "你好小海"},
        {"role": "assistant", "content": "今天怎么样？"},
    ]


@pytest.mark.asyncio
async def test_redis_lrange_failure_does_not_block(monkeypatch, llm_orchestrator):
    """redis.lrange 抛异常 → orchestrator 仍能返回回复，history 视为空。"""
    captured: dict[str, Any] = {}

    async def fake_chat(*, messages, trace_id, **_kwargs):
        captured["messages"] = messages
        return _LLMResultStub(content="still ok")

    monkeypatch.setattr(llm_orchestrator, "llm_chat", fake_chat)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)

    redis = _FakeRedis(RuntimeError("redis down"))

    reply = await llm_orchestrator.generate_reply(
        user_id="u",
        conversation_id="c",
        user_text="hi",
        trace_id="trace-redis-down",
        redis=redis,
    )

    assert reply == "still ok"
    # 没有历史，messages 只有 system + 当前 user；英文输入会触发 P3 语言约束。
    assert len(captured["messages"]) == 2
    assert captured["messages"][0]["role"] == "system"
    assert "language_code=en" in captured["messages"][0]["content"]
    assert captured["messages"][1] == {"role": "user", "content": "hi"}


@pytest.mark.asyncio
async def test_history_limit_zero_skips_redis(monkeypatch, llm_orchestrator):
    """history_limit=0 → 不调用 redis.lrange。"""
    captured: dict[str, Any] = {}

    async def fake_chat(*, messages, trace_id, **_kwargs):
        captured["messages"] = messages
        return _LLMResultStub(content="no-history")

    monkeypatch.setattr(llm_orchestrator, "llm_chat", fake_chat)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)

    class _NoLrangeRedis:
        async def lrange(self, *_a, **_k):
            raise AssertionError("lrange should not be called when history_limit=0")

    reply = await llm_orchestrator.generate_reply(
        user_id="u",
        conversation_id="c",
        user_text="hello",
        trace_id="trace-nohist",
        redis=_NoLrangeRedis(),
        history_limit=0,
    )

    assert reply == "no-history"
    assert len(captured["messages"]) == 2
    assert captured["messages"][0]["role"] == "system"
    assert "language_code=en" in captured["messages"][0]["content"]
    assert captured["messages"][1] == {"role": "user", "content": "hello"}


# ── D3-2：10 层 Prompt 结构 ─────────────────────────────────

@pytest.mark.asyncio
async def test_system_message_contains_all_layer_markers(monkeypatch, llm_orchestrator):
    """D3-2：system content 必含 9 个 ``## ===== Lx_NAME =====`` 标签（L8 在 messages 数组）。"""
    captured: dict[str, Any] = {}

    async def fake_chat(*, messages, trace_id, **_kwargs):
        captured["messages"] = messages
        return _LLMResultStub(content="ok")

    monkeypatch.setattr(llm_orchestrator, "llm_chat", fake_chat)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)

    reply = await llm_orchestrator.generate_reply(
        user_id="u",
        conversation_id="c",
        user_text="hi",
        trace_id="trace-layers",
    )

    assert reply == "ok"
    system = captured["messages"][0]
    assert system["role"] == "system"
    for label in (
        "L1_SAFETY",
        "L2_IDENTITY",
        "L3_CHARACTER",
        "L4_RELATIONSHIP",
        "L5_USER_PROFILE",
        "L6_MEMORY",
        "L7_CONVERSATION_STATE",
        "L9_FORMAT",
        "L10_ANCHOR",
    ):
        assert f"## ===== {label} =====" in system["content"], f"missing {label}"
    assert "L8_RECENT_CONTEXT" not in system["content"]  # L8 走 messages 数组


@pytest.mark.asyncio
async def test_db_assistant_reply_count_controls_first_35_boundary(
    monkeypatch, llm_orchestrator
):
    """Persisted 35 prior assistant replies means this is reply 36, so no first-35 block."""
    captured: dict[str, Any] = {}

    async def fake_chat(*, messages, trace_id, **_kwargs):
        captured["messages"] = messages
        return _LLMResultStub(content="ok")

    monkeypatch.setattr(llm_orchestrator, "llm_chat", fake_chat)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)
    monkeypatch.setattr(llm_orchestrator.settings, "MEMORY_RETRIEVE_IN_PROMPT", False)

    class _CountRow:
        def __getitem__(self, index):
            if index == 0:
                return 35
            raise IndexError(index)

    class _FakeExecResult:
        def __init__(self, row):
            self._row = row

        def fetchone(self):
            return self._row

    class _FakeDB:
        async def execute(self, stmt, params=None):
            sql = str(getattr(stmt, "text", stmt))
            if "FROM messages" in sql and "COUNT" in sql:
                return _FakeExecResult(_CountRow())
            return _FakeExecResult(None)

    reply = await llm_orchestrator.generate_reply(
        user_id="u",
        conversation_id="c",
        user_text="你喜欢什么？",
        trace_id="trace-count",
        db=_FakeDB(),
    )

    assert reply == "ok"
    system = captured["messages"][0]["content"]
    assert "前35次角色回复强约束" not in system
    assert "禁止表演化" in system


@pytest.mark.asyncio
async def test_db_loaded_character_and_profile_appear_in_prompt(
    monkeypatch, llm_orchestrator
):
    """D3-2：传入 db → orchestrator 查 character + profile → 渲染进 L3/L4/L5/L7。"""
    captured: dict[str, Any] = {}

    async def fake_chat(*, messages, trace_id, **_kwargs):
        captured["messages"] = messages
        return _LLMResultStub(content="ok")

    monkeypatch.setattr(llm_orchestrator, "llm_chat", fake_chat)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)

    class _FakeRow:
        def __init__(self, mapping: dict[str, Any]):
            self._mapping = mapping

    class _FakeExecResult:
        def __init__(self, row: _FakeRow | None):
            self._row = row

        def fetchone(self):
            return self._row

    class _FakeDB:
        """根据 SQL 关键词分发返回 character / user_profile 行。"""

        def __init__(self):
            self.calls: list[str] = []

        async def execute(self, stmt, params=None):  # noqa: D401 - test stub
            sql = str(getattr(stmt, "text", stmt))
            self.calls.append(sql)
            if "characters" in sql or "ch.id = c.character_id" in sql:
                return _FakeExecResult(
                    _FakeRow(
                        {
                            "id": "char-1",
                            "name": "Aria",
                            "region": "Shanghai",
                            "gentle_score": 80,
                            "flirt_score": 10,
                            "reply_length": "short",
                            "tone": "warm",
                            "emoji_frequency": "low",
                        }
                    )
                )
            if "user_profiles" in sql:
                return _FakeExecResult(
                    _FakeRow(
                        {
                            "relationship_stage": "S2",
                            "vip_level": 1,
                            "chat_style": "playful",
                            "interests": ["音乐"],
                            "forbidden_topics": ["政治"],
                            "preferences": {"nickname": "小海"},
                            "loneliness_score": 65,
                            "language": "en-US",
                        }
                    )
                )
            return _FakeExecResult(None)

    db = _FakeDB()

    reply = await llm_orchestrator.generate_reply(
        user_id="u",
        conversation_id="c",
        user_text="hi",
        trace_id="trace-db",
        db=db,
    )

    assert reply == "ok"
    system = captured["messages"][0]["content"]
    # L3: 角色
    assert "Aria" in system
    assert "Shanghai" in system
    assert "gentle=high" in system
    # L4: 关系 + VIP
    assert "S2" in system and "朋友" in system
    assert "VIP 等级：1" in system
    # L5: 用户画像
    assert "playful" in system
    assert "小海" in system
    assert "音乐" in system
    assert "政治" in system
    # L7: 孤独度 high band
    assert "high" in system
    # P3: users.language 注入回复语言约束
    assert "language_code=en" in system
    assert "English" in system
    # 至少两次 DB 查询（character + profile）
    assert len(db.calls) >= 2


@pytest.mark.asyncio
async def test_db_failures_do_not_break_reply(monkeypatch, llm_orchestrator):
    """D3-2：db.execute 抛异常 → orchestrator 仍能完成回复（降级为"未知"层）。"""

    async def fake_chat(*, messages, trace_id, **_kwargs):
        return _LLMResultStub(content="resilient")

    monkeypatch.setattr(llm_orchestrator, "llm_chat", fake_chat)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)

    class _BadDB:
        async def execute(self, *_a, **_k):
            raise RuntimeError("db down")

    reply = await llm_orchestrator.generate_reply(
        user_id="u",
        conversation_id="c",
        user_text="hi",
        trace_id="trace-db-down",
        db=_BadDB(),
    )
    assert reply == "resilient"


# ── D4-2：记忆检索注入 L6 ─────────────────────────────────


@pytest.mark.asyncio
async def test_memory_retrieve_skipped_when_flag_off(monkeypatch, llm_orchestrator):
    """MEMORY_RETRIEVE_IN_PROMPT=false → 不调 memory_retrieve（即使有 db）。"""

    async def boom_retrieve(**_kwargs):
        raise AssertionError("retrieve should not run")

    monkeypatch.setattr(llm_orchestrator, "memory_retrieve", boom_retrieve)
    monkeypatch.setattr(llm_orchestrator.settings, "MEMORY_RETRIEVE_IN_PROMPT", False)

    async def fake_chat(*, messages, trace_id, **_kwargs):
        return _LLMResultStub(content="ok")

    monkeypatch.setattr(llm_orchestrator, "llm_chat", fake_chat)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)

    class _EmptyDB:
        async def execute(self, *_a, **_k):
            class _R:
                def fetchone(self):
                    return None

            return _R()

    reply = await llm_orchestrator.generate_reply(
        user_id="u",
        conversation_id="c",
        user_text="hello",
        trace_id="t-skip",
        db=_EmptyDB(),
    )
    assert reply == "ok"


@pytest.mark.asyncio
async def test_memory_retrieve_injected_into_prompt_when_enabled(
    monkeypatch, llm_orchestrator
):
    """MEMORY_RETRIEVE_IN_PROMPT=true → retrieve 入参与 API 一致，L6 出现记忆正文。"""
    from datetime import datetime, timezone

    from services.memory_retriever import MemoryHit, RetrieveResult

    captured: dict[str, Any] = {}

    async def fake_chat(*, messages, trace_id, **_kwargs):
        captured["messages"] = messages
        return _LLMResultStub(content="ok")

    async def fake_retrieve(**kwargs):
        assert kwargs["user_id"] == "u1"
        assert kwargs["query_text"] == "remember my dog"
        assert kwargs["k_final"] == llm_orchestrator.settings.MEMORY_RETRIEVE_TOP_K
        assert kwargs["k_candidates"] == llm_orchestrator.settings.MEMORY_RETRIEVE_K_CANDIDATES
        assert kwargs["memory_types"] is None
        assert kwargs["min_importance"] == 0.0
        assert kwargs["include_global"] is True
        assert kwargs["touch_last_used"] is True
        assert kwargs["character_id"] == "char-9"
        hit = MemoryHit(
            id="m1",
            content="User loves a golden retriever named Max",
            memory_type="fact",
            importance_score=8.0,
            confidence_score=0.9,
            emotion_tags=[],
            created_at=datetime.now(timezone.utc),
            last_used_at=None,
            similarity=0.88,
            final_score=0.91,
        )
        return RetrieveResult(hits=[hit], embedding_used=True)

    monkeypatch.setattr(llm_orchestrator, "memory_retrieve", fake_retrieve)
    monkeypatch.setattr(llm_orchestrator, "llm_chat", fake_chat)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)
    monkeypatch.setattr(llm_orchestrator.settings, "MEMORY_RETRIEVE_IN_PROMPT", True)
    monkeypatch.setattr(llm_orchestrator.settings, "MEMORY_RETRIEVE_TOP_K", 10)
    monkeypatch.setattr(llm_orchestrator.settings, "MEMORY_RETRIEVE_K_CANDIDATES", 30)

    async def _pass_refresh(**kwargs):
        return kwargs["profile_row"]

    monkeypatch.setattr(llm_orchestrator, "refresh_loneliness_score", _pass_refresh)

    class _FakeRow:
        def __init__(self, mapping: dict[str, Any]):
            self._mapping = mapping

    class _FakeExecResult:
        def __init__(self, row):
            self._row = row

        def fetchone(self):
            return self._row

    class _FakeDB:
        async def execute(self, stmt, params=None):
            sql = str(getattr(stmt, "text", stmt))
            if "ch.id = c.character_id" in sql or "characters" in sql:
                return _FakeExecResult(
                    _FakeRow({"id": "char-9", "name": "Aria", "region": "EU"})
                )
            if "user_profiles" in sql:
                return _FakeExecResult(_FakeRow({"loneliness_score": 40}))
            return _FakeExecResult(None)

    reply = await llm_orchestrator.generate_reply(
        user_id="u1",
        conversation_id="c1",
        user_text="remember my dog",
        trace_id="t-mem",
        db=_FakeDB(),
    )

    assert reply == "ok"
    system = captured["messages"][0]["content"]
    assert "L6_MEMORY" in system
    assert "golden retriever" in system


@pytest.mark.asyncio
async def test_character_context_falls_back_to_profile_current_character(
    monkeypatch, llm_orchestrator
):
    """Telegram conversations may not carry character_id; use user profile assignment."""
    captured: dict[str, Any] = {}

    async def fake_chat(*, messages, trace_id, **_kwargs):
        captured["messages"] = messages
        return _LLMResultStub(content="ok")

    async def _pass_refresh(**kwargs):
        return kwargs["profile_row"]

    monkeypatch.setattr(llm_orchestrator, "llm_chat", fake_chat)
    monkeypatch.setattr(llm_orchestrator, "refresh_loneliness_score", _pass_refresh)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)
    monkeypatch.setattr(llm_orchestrator.settings, "MEMORY_RETRIEVE_IN_PROMPT", False)

    class _FakeRow:
        def __init__(self, mapping: dict[str, Any]):
            self._mapping = mapping

    class _FakeExecResult:
        def __init__(self, row):
            self._row = row

        def fetchone(self):
            return self._row

    class _FakeDB:
        async def execute(self, stmt, params=None):
            sql = str(getattr(stmt, "text", stmt))
            if "LEFT JOIN characters ch ON ch.id = c.character_id" in sql:
                return _FakeExecResult(None)
            if "FROM user_profiles" in sql:
                return _FakeExecResult(
                    _FakeRow(
                        {
                            "current_character_id": "char-profile",
                            "loneliness_score": 40,
                        }
                    )
                )
            if "SELECT * FROM characters WHERE id" in sql:
                return _FakeExecResult(
                    _FakeRow(
                        {
                            "id": "char-profile",
                            "name": "Mira",
                            "profile_details": {
                                "height": "169cm",
                                "relationship_status": "没有男朋友",
                            },
                        }
                    )
                )
            return _FakeExecResult(None)

    reply = await llm_orchestrator.generate_reply(
        user_id="u1",
        conversation_id="conv-without-character",
        user_text="你多高？",
        trace_id="t-profile-character",
        db=_FakeDB(),
    )

    assert reply == "ok"
    system = captured["messages"][0]["content"]
    assert "Mira" in system
    assert "身高：169cm" in system
    assert "感情状态：没有男朋友" in system


@pytest.mark.asyncio
async def test_profile_current_character_overrides_conversation_character(
    monkeypatch, llm_orchestrator
):
    """Admin role switch should make profile assignment the prompt source of truth."""
    captured: dict[str, Any] = {}

    async def fake_chat(*, messages, trace_id, **_kwargs):
        captured["messages"] = messages
        return _LLMResultStub(content="ok")

    async def _pass_refresh(**kwargs):
        return kwargs["profile_row"]

    monkeypatch.setattr(llm_orchestrator, "llm_chat", fake_chat)
    monkeypatch.setattr(llm_orchestrator, "refresh_loneliness_score", _pass_refresh)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)
    monkeypatch.setattr(llm_orchestrator.settings, "MEMORY_RETRIEVE_IN_PROMPT", False)

    class _FakeRow:
        def __init__(self, mapping: dict[str, Any]):
            self._mapping = mapping

    class _FakeExecResult:
        def __init__(self, row):
            self._row = row

        def fetchone(self):
            return self._row

    class _FakeDB:
        async def execute(self, stmt, params=None):
            sql = str(getattr(stmt, "text", stmt))
            if "FROM user_profiles" in sql:
                return _FakeExecResult(
                    _FakeRow(
                        {
                            "current_character_id": "char-new",
                            "loneliness_score": 40,
                        }
                    )
                )
            if "SELECT * FROM characters WHERE id" in sql:
                return _FakeExecResult(
                    _FakeRow(
                        {
                            "id": "char-new",
                            "name": "NewRole",
                            "profile_details": {"height": "169cm"},
                        }
                    )
                )
            if "LEFT JOIN characters ch ON ch.id = c.character_id" in sql:
                return _FakeExecResult(
                    _FakeRow(
                        {
                            "id": "char-old",
                            "name": "OldRole",
                            "profile_details": {"height": "150cm"},
                        }
                    )
                )
            return _FakeExecResult(None)

    await llm_orchestrator.generate_reply(
        user_id="u1",
        conversation_id="conv-with-old-character",
        user_text="你多高？",
        trace_id="t-profile-priority",
        db=_FakeDB(),
    )

    system = captured["messages"][0]["content"]
    assert "NewRole" in system
    assert "身高：169cm" in system
    assert "OldRole" not in system
    assert "150cm" not in system


@pytest.mark.asyncio
async def test_memory_consistency_filters_conflicting_hit_before_l6(
    monkeypatch, llm_orchestrator
):
    """任务卡 9：感情结束信号 + 记忆仍写伴侣 → 该条不进 L6，其余仍注入。"""
    from datetime import datetime, timezone

    from services.memory_retriever import MemoryHit, RetrieveResult

    captured: dict[str, Any] = {}

    async def fake_chat(*, messages, trace_id, **_kwargs):
        captured["messages"] = messages
        return _LLMResultStub(content="ok")

    async def fake_retrieve(**_kwargs):
        h_bad = MemoryHit(
            id="m1",
            content="用户和男朋友感情很好，每周约会",
            memory_type="relationship",
            importance_score=9.0,
            confidence_score=0.9,
            emotion_tags=[],
            created_at=datetime.now(timezone.utc),
            last_used_at=None,
            similarity=0.9,
            final_score=0.95,
        )
        h_ok = MemoryHit(
            id="m2",
            content="用户喜欢喝燕麦拿铁",
            memory_type="preference",
            importance_score=6.0,
            confidence_score=0.8,
            emotion_tags=[],
            created_at=datetime.now(timezone.utc),
            last_used_at=None,
            similarity=0.5,
            final_score=0.6,
        )
        return RetrieveResult(hits=[h_bad, h_ok], embedding_used=False)

    monkeypatch.setattr(llm_orchestrator, "memory_retrieve", fake_retrieve)
    monkeypatch.setattr(llm_orchestrator, "llm_chat", fake_chat)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)
    monkeypatch.setattr(llm_orchestrator.settings, "MEMORY_RETRIEVE_IN_PROMPT", True)
    monkeypatch.setattr(llm_orchestrator.settings, "MEMORY_CONSISTENCY_ENABLED", True)

    async def _pass_refresh(**kwargs):
        return kwargs["profile_row"]

    monkeypatch.setattr(llm_orchestrator, "refresh_loneliness_score", _pass_refresh)

    class _FakeRow:
        def __init__(self, mapping: dict[str, Any]):
            self._mapping = mapping

    class _FakeExecResult:
        def __init__(self, row):
            self._row = row

        def fetchone(self):
            return self._row

    class _FakeDB:
        async def execute(self, stmt, params=None):
            sql = str(getattr(stmt, "text", stmt))
            if "characters" in sql:
                return _FakeExecResult(_FakeRow({"id": "c2", "name": "Aria"}))
            if "user_profiles" in sql:
                return _FakeExecResult(_FakeRow({"loneliness_score": 40.0}))
            return _FakeExecResult(None)

    await llm_orchestrator.generate_reply(
        user_id="u1",
        conversation_id="c1",
        user_text="我们分手了，别再提他",
        trace_id="t-consistency",
        db=_FakeDB(),
    )

    system = captured["messages"][0]["content"]
    assert "燕麦拿铁" in system
    assert "男朋友" not in system


# ── D4-3 / D4-4：loneliness 主链路写回（先于 D4-2 retrieve）────────────────


@pytest.mark.asyncio
async def test_refresh_loneliness_score_runs_before_memory_retrieve(
    monkeypatch, llm_orchestrator
):
    """RUNBOOK 顺序：refresh_loneliness_score → memory_retrieve。"""
    from services.memory_retriever import RetrieveResult

    order: list[str] = []

    async def fake_refresh(**kwargs):
        order.append("loneliness")
        return kwargs["profile_row"]

    async def fake_retrieve(**_kwargs):
        order.append("retrieve")
        return RetrieveResult(hits=[])

    monkeypatch.setattr(llm_orchestrator, "refresh_loneliness_score", fake_refresh)
    monkeypatch.setattr(llm_orchestrator, "memory_retrieve", fake_retrieve)
    monkeypatch.setattr(llm_orchestrator.settings, "MEMORY_RETRIEVE_IN_PROMPT", True)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)

    async def fake_chat(*, messages, trace_id, **_kwargs):
        return _LLMResultStub(content="ok")

    monkeypatch.setattr(llm_orchestrator, "llm_chat", fake_chat)

    class _FakeRow:
        def __init__(self, mapping: dict[str, Any]):
            self._mapping = mapping

    class _FakeExecResult:
        def __init__(self, row):
            self._row = row

        def fetchone(self):
            return self._row

    class _FakeDB:
        async def execute(self, stmt, params=None):
            sql = str(getattr(stmt, "text", stmt))
            if "ch.id = c.character_id" in sql or "characters" in sql:
                return _FakeExecResult(_FakeRow({"id": "cid", "name": "Aria"}))
            if "user_profiles" in sql:
                return _FakeExecResult(_FakeRow({"loneliness_score": 40.0}))
            return _FakeExecResult(None)

    await llm_orchestrator.generate_reply(
        user_id="u1",
        conversation_id="c1",
        user_text="hello there",
        trace_id="t-order",
        db=_FakeDB(),
    )
    assert order == ["loneliness", "retrieve"]


@pytest.mark.asyncio
async def test_refresh_loneliness_score_skipped_without_profile(
    monkeypatch, llm_orchestrator
):
    """无 user_profiles 行时不调 refresh（仍可调 retrieve）。"""

    async def boom_refresh(**_kwargs):
        raise AssertionError("refresh should not run without profile")

    monkeypatch.setattr(llm_orchestrator, "refresh_loneliness_score", boom_refresh)
    monkeypatch.setattr(llm_orchestrator.settings, "MEMORY_RETRIEVE_IN_PROMPT", False)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)

    async def fake_chat(*, messages, trace_id, **_kwargs):
        return _LLMResultStub(content="ok")

    monkeypatch.setattr(llm_orchestrator, "llm_chat", fake_chat)

    class _FakeRow:
        def __init__(self, mapping: dict[str, Any]):
            self._mapping = mapping

    class _FakeExecResult:
        def __init__(self, row):
            self._row = row

        def fetchone(self):
            return self._row

    class _FakeDBCharOnly:
        async def execute(self, stmt, params=None):
            sql = str(getattr(stmt, "text", stmt))
            if "ch.id = c.character_id" in sql or "characters" in sql:
                return _FakeExecResult(_FakeRow({"id": "cid", "name": "Aria"}))
            if "user_profiles" in sql:
                return _FakeExecResult(None)
            return _FakeExecResult(None)

    await llm_orchestrator.generate_reply(
        user_id="u1",
        conversation_id="c1",
        user_text="hi",
        trace_id="t-noprof",
        db=_FakeDBCharOnly(),
    )


@pytest.mark.asyncio
async def test_refresh_loneliness_score_updates_l7_band(monkeypatch, llm_orchestrator):
    """mock refresh 提高 loneliness_score → L7 分段变化。"""

    async def bump_refresh(**kwargs):
        p = dict(kwargs["profile_row"])
        p["loneliness_score"] = 72.0
        return p

    async def noop_retrieve(**_kwargs):
        from services.memory_retriever import RetrieveResult

        return RetrieveResult(hits=[])

    monkeypatch.setattr(llm_orchestrator, "refresh_loneliness_score", bump_refresh)
    monkeypatch.setattr(llm_orchestrator, "memory_retrieve", noop_retrieve)
    monkeypatch.setattr(llm_orchestrator.settings, "MEMORY_RETRIEVE_IN_PROMPT", True)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)

    captured: dict[str, Any] = {}

    async def fake_chat(*, messages, trace_id, **_kwargs):
        captured["messages"] = messages
        return _LLMResultStub(content="ok")

    monkeypatch.setattr(llm_orchestrator, "llm_chat", fake_chat)

    class _FakeRow:
        def __init__(self, mapping: dict[str, Any]):
            self._mapping = mapping

    class _FakeExecResult:
        def __init__(self, row):
            self._row = row

        def fetchone(self):
            return self._row

    class _FakeDB:
        async def execute(self, stmt, params=None):
            sql = str(getattr(stmt, "text", stmt))
            if "ch.id = c.character_id" in sql or "characters" in sql:
                return _FakeExecResult(_FakeRow({"id": "cid", "name": "Aria"}))
            if "user_profiles" in sql:
                return _FakeExecResult(_FakeRow({"loneliness_score": 40.0}))
            return _FakeExecResult(None)

    await llm_orchestrator.generate_reply(
        user_id="u1",
        conversation_id="c1",
        user_text="y",
        trace_id="t-l7",
        db=_FakeDB(),
    )
    system = captured["messages"][0]["content"]
    assert "72.0" in system or "high" in system


@pytest.mark.asyncio
async def test_relationship_stage_auto_adjust_updates_prompt_l4(
    monkeypatch, llm_orchestrator
):
    """REL-01：自动升阶段后，当轮 L4 使用更新后的 relationship_stage。"""
    captured: dict[str, Any] = {}

    async def fake_chat(*, messages, trace_id, **_kwargs):
        captured["messages"] = messages
        return _LLMResultStub(content="ok")

    async def pass_refresh(**kwargs):
        return kwargs["profile_row"]

    monkeypatch.setattr(llm_orchestrator, "llm_chat", fake_chat)
    monkeypatch.setattr(llm_orchestrator, "refresh_loneliness_score", pass_refresh)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)
    monkeypatch.setattr(llm_orchestrator.settings, "MEMORY_RETRIEVE_IN_PROMPT", False)
    monkeypatch.setattr(llm_orchestrator.settings, "POLICY_SERVICE_ENABLED", False)
    monkeypatch.setattr(llm_orchestrator.settings, "REL_STAGE_AUTO_ENABLED", True)
    monkeypatch.setattr(llm_orchestrator.settings, "REL_STAGE_ALLOW_DOWNGRADE", True)
    monkeypatch.setattr(llm_orchestrator.settings, "REL_STAGE_INITIATION_S1", 10.0)
    monkeypatch.setattr(llm_orchestrator.settings, "REL_STAGE_INITIATION_S2", 30.0)
    monkeypatch.setattr(llm_orchestrator.settings, "REL_STAGE_INITIATION_S3", 55.0)
    monkeypatch.setattr(llm_orchestrator.settings, "REL_STAGE_INITIATION_S4", 78.0)
    monkeypatch.setattr(llm_orchestrator.settings, "REL_STAGE_VIP_MIN_FOR_S1", 1)

    class _FakeRow:
        def __init__(self, mapping: dict[str, Any]):
            self._mapping = mapping

    class _FakeExecResult:
        def __init__(self, row):
            self._row = row

        def fetchone(self):
            return self._row

    class _FakeDB:
        def __init__(self):
            self.commits = 0

        async def execute(self, stmt, params=None):
            sql = str(getattr(stmt, "text", stmt))
            if "ch.id = c.character_id" in sql or "characters" in sql:
                return _FakeExecResult(_FakeRow({"id": "cid", "name": "Aria"}))
            if sql.lstrip().upper().startswith("SELECT") and "user_profiles" in sql:
                return _FakeExecResult(
                    _FakeRow(
                        {
                            "relationship_stage": "S1",
                            "initiation_score": 60.0,
                            "vip_level": 0,
                            "loneliness_score": 40.0,
                        }
                    )
                )
            return _FakeExecResult(None)

        async def commit(self):
            self.commits += 1

    db = _FakeDB()
    await llm_orchestrator.generate_reply(
        user_id="00000000-0000-0000-0000-000000000001",
        conversation_id="c1",
        user_text="hello",
        trace_id="t-rel",
        db=db,
    )

    system = captured["messages"][0]["content"]
    assert "关系阶段：S3" in system
    assert "亲近" in system
    assert db.commits == 1
