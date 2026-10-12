import asyncio
from unittest.mock import AsyncMock, patch

from services import ai_message_limit
from services.app_download_conversion import (
    AppDownloadDecision,
    decision_bypasses_link_cooldown,
    is_t1_sixth_message_decision,
)
from services.human_takeover_gate import evaluate_human_takeover_gate, ensure_t1_manual_handoff
from services.mtproto import auto_reply
from services import profile_intake
import inspect


def test_t1_and_non_t1_limits() -> None:
    assert ai_message_limit.T1_AI_MESSAGE_LIMIT == 6
    assert ai_message_limit.T1_COUNTRY_ASK_WINDOW == 5
    assert ai_message_limit.NON_T1_AI_MESSAGE_LIMIT == 20
    assert ai_message_limit.T1_HANDOFF_TIMEOUT_SECONDS == 600


def test_t1_count_includes_profile_intake_excludes_fixed_and_assets() -> None:
    sql = ai_message_limit._T1_COUNTED_AI_MODEL_SQL
    assert "fixed_auto_reply" in sql
    assert "script_asset" in sql
    assert "auto_delivery_worker" in sql
    assert "profile_intake" not in sql


def test_quota_t1_sixth_slot() -> None:
    with patch.object(ai_message_limit, "load_t1_countries", return_value=frozenset({"US"})):
        quota = ai_message_limit.quota_from_row(
            "u1",
            {
                "country_code": "US",
                "country_source": "chat_answer",
                "system_sent_count": 5,
                "realtime_sent_count": 3,
            },
        )
    assert quota.is_t1 is True
    assert quota.country_known is True
    assert quota.sent_count == 5
    assert quota.limit == 6
    assert quota.is_sixth_t1_slot is True
    assert quota.must_ask_country is False


def test_quota_weak_country_still_asks_and_uses_non_t1_limit() -> None:
    with patch.object(ai_message_limit, "load_t1_countries", return_value=frozenset({"US"})):
        quota = ai_message_limit.quota_from_row(
            "u1",
            {
                "country_code": "US",
                "country_source": "language_fallback",
                "system_sent_count": 2,
                "realtime_sent_count": 1,
            },
        )
    assert quota.is_t1 is False
    assert quota.country_known is False
    assert quota.must_ask_country is True
    assert quota.limit == 20
    assert quota.sent_count == 1


def test_quota_unknown_stops_asking_after_five_system_messages() -> None:
    quota = ai_message_limit.quota_from_row(
        "u1",
        {
            "country_code": None,
            "country_source": "",
            "system_sent_count": 5,
            "realtime_sent_count": 2,
        },
    )
    assert quota.must_ask_country is False
    assert quota.is_t1 is False
    assert quota.limit == 20


def test_t1_sixth_decision_bypasses_link_cooldown() -> None:
    decision = AppDownloadDecision(
        content="open here https://example.com",
        category_key="app_download_direct_cta",
        script_hit_id="t1-sixth",
        assets=[],
        user_level="C",
        persona_slug=None,
        intent="t1_sixth_message_link",
        scene_step="t1_sixth_message_link",
        country_code="US",
        age=28,
        is_t1_country=True,
        language="en",
    )
    assert is_t1_sixth_message_decision(decision) is True
    assert decision_bypasses_link_cooldown(decision) is True


def test_gate_no_longer_handoffs_t1_before_ai_cap() -> None:
    source = inspect.getsource(evaluate_human_takeover_gate)
    assert "is_t1_country" not in source
    assert "is_t1_manual_handoff" in source
    assert "ensure_t1_manual_handoff" not in source
    assert callable(ensure_t1_manual_handoff)


def test_write_country_code_does_not_force_waiting_operator() -> None:
    source = inspect.getsource(profile_intake.write_country_code)
    assert "WAITING_OPERATOR" not in source
    assert "t1_country_manual_chat" not in source
    assert "t1_identified_at" in source


def _t1_quota(*, sent_count: int) -> ai_message_limit.AIMessageQuota:
    return ai_message_limit.AIMessageQuota(
        user_id="u1",
        country_code="FR",
        country_source="telegram_phone_country",
        country_known=True,
        is_t1=True,
        sent_count=sent_count,
        system_sent_count=sent_count,
        limit=ai_message_limit.T1_AI_MESSAGE_LIMIT,
    )


def test_maybe_handoff_t1_after_six_messages() -> None:
    async def _run() -> None:
        handoff = AsyncMock()
        with patch.object(
            ai_message_limit,
            "inspect_ai_message_quota",
            AsyncMock(return_value=_t1_quota(sent_count=6)),
        ), patch.object(
            ai_message_limit,
            "t1_handoff_elapsed_seconds",
            AsyncMock(return_value=60.0),
        ), patch(
            "services.human_takeover_gate.ensure_t1_manual_handoff",
            handoff,
        ):
            moved = await ai_message_limit.maybe_handoff_t1_after_ai_cap(
                object(),
                user_id="u1",
                conversation_id="c1",
            )
        assert moved is True
        handoff.assert_awaited_once()

    asyncio.run(_run())


def test_maybe_handoff_t1_timeout_before_six() -> None:
    async def _run() -> None:
        handoff = AsyncMock()
        with patch.object(
            ai_message_limit,
            "inspect_ai_message_quota",
            AsyncMock(return_value=_t1_quota(sent_count=2)),
        ), patch.object(
            ai_message_limit,
            "t1_handoff_elapsed_seconds",
            AsyncMock(return_value=601.0),
        ), patch(
            "services.human_takeover_gate.ensure_t1_manual_handoff",
            handoff,
        ):
            moved = await ai_message_limit.maybe_handoff_t1_after_ai_cap(
                object(),
                user_id="u1",
                conversation_id="c1",
            )
        assert moved is True
        handoff.assert_awaited_once()

    asyncio.run(_run())


def test_maybe_handoff_t1_does_not_timeout_at_five_minutes() -> None:
    async def _run() -> None:
        handoff = AsyncMock()
        with patch.object(
            ai_message_limit,
            "inspect_ai_message_quota",
            AsyncMock(return_value=_t1_quota(sent_count=2)),
        ), patch.object(
            ai_message_limit,
            "t1_handoff_elapsed_seconds",
            AsyncMock(return_value=300.0),
        ), patch(
            "services.human_takeover_gate.ensure_t1_manual_handoff",
            handoff,
        ):
            moved = await ai_message_limit.maybe_handoff_t1_after_ai_cap(
                object(),
                user_id="u1",
                conversation_id="c1",
            )
        assert moved is False
        handoff.assert_not_awaited()

    asyncio.run(_run())


def test_t1_timeout_worker_query_excludes_weak_country() -> None:
    source = inspect.getsource(ai_message_limit.list_t1_timeout_handoff_candidates)
    assert "language_fallback" in source
    assert "telegram_language_code" in source
    assert "timeout_seconds" in source
    assert "AI_ACTIVE" in source


def test_runtime_checks_t1_handoff_before_generating() -> None:
    auto_src = inspect.getsource(auto_reply._deliver_mtproto_inbound_reply)
    assert auto_src.index("maybe_handoff_t1_after_ai_cap") < auto_src.index("generate_reply(")
    worker_src = inspect.getsource(
        __import__(
            "services.human_takeover_release_worker",
            fromlist=["run_one_tick"],
        ).run_one_tick
    )
    assert "handoff_t1_timeout_candidates" in worker_src
    assert worker_src.index("handoff_t1_timeout_candidates") < worker_src.index(
        "list_idle_human_takeover_candidates"
    )


def test_country_ask_window_keeps_asking_in_first_five() -> None:
    assert auto_reply._keep_asking_country(country_prompt_count=3, ai_system_sent_count=4) is True
    assert auto_reply._keep_asking_country(country_prompt_count=3, ai_system_sent_count=5) is False
    assert auto_reply._keep_asking_country(country_prompt_count=2, ai_system_sent_count=None) is True
    assert auto_reply._keep_asking_country(country_prompt_count=3, ai_system_sent_count=None) is False


def test_limit_error_distinguishes_t1() -> None:
    err = ai_message_limit.AIMessageLimitReached(
        user_id="u1",
        sent_count=6,
        limit=6,
        is_t1=True,
    )
    assert err.is_t1 is True
    assert "T1" in str(err)