"""POL-01：Policy Service 七条件与建单门控。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.policy_service import (
    detect_keyword_human_request,
    evaluate_policy_hits,
    maybe_create_policy_handoff,
    pick_best_hit,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Can I talk to a human please?", True),
        ("我想转人工", True),
        ("hello there", False),
        ("", False),
    ],
)
def test_detect_keyword_human_request(text: str, expected: bool):
    assert detect_keyword_human_request(text) is expected


def test_evaluate_policy_hits_multiple_and_pick_best():
    hits = evaluate_policy_hits(
        user_text="talk to a human",
        profile={"risk_score": 80, "loneliness_score": 90, "vip_level": 2},
        user_risk_level="high",
        is_minor_suspected=False,
        handoff_count=0,
    )
    codes = {h.code for h in hits}
    assert "keyword_human" in codes
    assert "account_risk_level" in codes
    assert "profile_risk_score" in codes
    assert "loneliness_high" in codes
    assert "vip_tier" in codes
    best = pick_best_hit(hits)
    assert best is not None
    assert best.code == "keyword_human"
    assert best.priority == "P1"


def test_evaluate_initiation_hot():
    hits = evaluate_policy_hits(
        user_text="hi",
        profile={
            "initiation_score": 70.0,
            "trigger_threshold": 65.0,
            "risk_score": 0,
            "loneliness_score": 0,
            "vip_level": 0,
        },
        user_risk_level="normal",
        is_minor_suspected=False,
        handoff_count=0,
    )
    assert any(h.code == "initiation_hot" for h in hits)


def test_safeguard_minor():
    hits = evaluate_policy_hits(
        user_text="x",
        profile=None,
        user_risk_level="normal",
        is_minor_suspected=True,
        handoff_count=0,
    )
    assert pick_best_hit(hits).code == "safeguard"


def test_safeguard_handoff_storm():
    hits = evaluate_policy_hits(
        user_text="x",
        profile=None,
        user_risk_level="normal",
        is_minor_suspected=False,
        handoff_count=5,
    )
    assert pick_best_hit(hits).code == "safeguard"


@pytest.mark.asyncio
async def test_maybe_create_policy_handoff_disabled():
    db = MagicMock()
    with patch("services.policy_service.settings") as s:
        s.POLICY_SERVICE_ENABLED = False
        out = await maybe_create_policy_handoff(
            db,
            user_id="u",
            conversation_id="c",
            user_text="talk to human",
            profile_row={},
            trace_id="t",
        )
    assert out is None
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_create_policy_handoff_inserts_and_commits():
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()

    async def exec_side(sql, params=None):
        q = str(sql)
        if "FROM handoff_tasks" in q and "conversation_id" in q:
            r = MagicMock()
            r.fetchone = MagicMock(return_value=None)
            return r
        if "FROM users u" in q:
            r = MagicMock()
            row = MagicMock()
            row._mapping = {
                "risk_level": "normal",
                "is_minor_suspected": False,
                "handoff_count": 0,
                "state": "AI_ACTIVE",
            }
            r.fetchone = MagicMock(return_value=row)
            return r
        r = MagicMock()
        r.fetchone = MagicMock(return_value=None)
        return r

    db.execute.side_effect = exec_side

    with patch("services.policy_service.settings") as s:
        s.POLICY_SERVICE_ENABLED = True
        s.POLICY_RISK_SCORE_THRESHOLD = 75
        s.POLICY_LONELINESS_THRESHOLD = 82.0
        s.POLICY_VIP_LEVEL_THRESHOLD = 1
        s.POLICY_HANDOFF_COUNT_THRESHOLD = 3
        tid = await maybe_create_policy_handoff(
            db,
            user_id="u",
            conversation_id="c",
            user_text="I need to talk to a human",
            profile_row={"risk_score": 0},
            trace_id="t",
        )
    assert tid is not None
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_reply_invokes_policy_when_enabled():
    from services.llm_orchestrator import generate_reply

    db = MagicMock()
    db.execute = AsyncMock()

    async def exec_map(sql, params=None):
        q = str(sql)
        r = MagicMock()
        if "FROM conversations c" in q and "LEFT JOIN characters" in q:
            row = MagicMock()
            row._mapping = {"id": "char-1", "name": "Aria"}
            r.fetchone = MagicMock(return_value=row)
            return r
        if "FROM user_profiles" in q:
            row = MagicMock()
            row._mapping = {
                "user_id": "u1",
                "loneliness_score": 40.0,
                "risk_score": 0,
                "relationship_stage": "S0",
            }
            r.fetchone = MagicMock(return_value=row)
            return r
        r = MagicMock()
        r.fetchone = MagicMock(return_value=None)
        return r

    db.execute.side_effect = exec_map
    db.commit = AsyncMock()

    with (
        patch("services.llm_orchestrator.settings") as orch_settings,
        patch(
            "services.llm_orchestrator.refresh_loneliness_score",
            new_callable=AsyncMock,
        ) as mock_refresh,
        patch(
            "services.policy_service.maybe_create_policy_handoff",
            new_callable=AsyncMock,
        ) as mock_policy,
        patch("services.llm_orchestrator.llm_chat", new_callable=AsyncMock) as mock_llm,
    ):
        orch_settings.LLM_ECHO_FALLBACK = True
        orch_settings.MEMORY_RETRIEVE_IN_PROMPT = False
        orch_settings.LONELINESS_UTTERANCE_ENABLED = False
        orch_settings.POLICY_SERVICE_ENABLED = True

        mock_refresh.return_value = {
            "user_id": "u1",
            "loneliness_score": 40.0,
            "risk_score": 0,
            "relationship_stage": "S0",
        }
        mock_policy.return_value = None

        class _Res:
            error = None
            content = "ok"
            model_used = "m"
            fallback_used = False
            usage = {}

        mock_llm.return_value = _Res()

        out = await generate_reply(
            user_id="u1",
            conversation_id="c1",
            user_text="hello",
            trace_id="tr",
            redis=None,
            db=db,
        )

    assert out == "ok"
    mock_policy.assert_awaited_once()
