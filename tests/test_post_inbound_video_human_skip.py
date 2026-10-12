from services.call_broadcast.post_inbound_video_fixed_messages import (
    maybe_send_03_on_later_inbound_call,
    should_skip_post_video_auto_send,
)
from services.human_takeover_gate import HUMAN_CONTROL_STATES
import inspect


def test_skip_when_waiting_operator() -> None:
    assert should_skip_post_video_auto_send(conversation_state="WAITING_OPERATOR") is True
    assert should_skip_post_video_auto_send(conversation_state="HUMAN_LOCKED") is True


def test_skip_when_operator_already_replied() -> None:
    assert should_skip_post_video_auto_send(
        conversation_state="AI_ACTIVE",
        operator_replied=True,
    ) is True


def test_allow_when_ai_active_and_no_operator() -> None:
    assert should_skip_post_video_auto_send(
        conversation_state="AI_ACTIVE",
        operator_replied=False,
    ) is False


def test_human_control_states_cover_operator_queue() -> None:
    assert HUMAN_CONTROL_STATES == frozenset({"HUMAN_LOCKED", "WAITING_OPERATOR"})


def test_later_inbound_03_checks_human_control() -> None:
    source = inspect.getsource(maybe_send_03_on_later_inbound_call)
    assert "should_skip_post_video_auto_send" in source
    assert "skip_human_control" in source
    assert "skip_03_debounce" in source
    assert "RETURNING id::text" in source
