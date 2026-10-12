from services.call_broadcast import incoming_listener
from services.call_broadcast.incoming_listener import (
    _incoming_failure_requires_listener_reset,
)


def test_expected_call_outcomes_do_not_reset_listener() -> None:
    incoming_listener._consecutive_answer_timeouts.clear()
    for message in (
        "The user 123 is busy",
        "Call declined by 123",
        "Call discarded by 123",
        "The call was already declined (caused by AcceptCallRequest)",
    ):
        assert not _incoming_failure_requires_listener_reset(RuntimeError(message))


def test_single_answer_timeout_does_not_reset_listener() -> None:
    incoming_listener._consecutive_answer_timeouts.clear()
    assert not _incoming_failure_requires_listener_reset(
        RuntimeError("call not answered for chat_id=123"),
        account_id="acct-a",
    )


def test_repeated_answer_timeout_resets_listener() -> None:
    incoming_listener._consecutive_answer_timeouts.clear()
    first = RuntimeError("call not answered for chat_id=123")
    second = RuntimeError("call not answered for chat_id=123")
    assert not _incoming_failure_requires_listener_reset(first, account_id="acct-a")
    assert _incoming_failure_requires_listener_reset(second, account_id="acct-a")


def test_transport_failure_resets_listener() -> None:
    incoming_listener._consecutive_answer_timeouts.clear()
    assert _incoming_failure_requires_listener_reset(RuntimeError("RTC transport closed"))
