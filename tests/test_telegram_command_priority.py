from services.telegram_command_gateway import INTERACTIVE_COMMAND_TYPES, priority_for_command
from services.runtime_command_consumer import REAL_CLAIM_SQL, _is_operator_confirmed


def test_delete_and_disconnect_jump_the_queue() -> None:
    assert {"delete_account", "disconnect_account"} <= INTERACTIVE_COMMAND_TYPES
    assert priority_for_command("delete_account") == 100
    assert priority_for_command("disconnect_account") == 100
    assert priority_for_command("connect_account") == 0
    assert priority_for_command("send_message") == 0
    assert priority_for_command("delete_account", 7) == 7


def test_real_claim_sql_keeps_operator_sends_off_the_slow_loop() -> None:
    assert "only_interactive" in REAL_CLAIM_SQL
    assert "operator_confirmed" in REAL_CLAIM_SQL
    assert "send_media" in REAL_CLAIM_SQL
    assert "delete_account" in REAL_CLAIM_SQL
    assert "ORDER BY priority DESC" in REAL_CLAIM_SQL
    assert "CAST(:only_interactive AS integer) = 0" in REAL_CLAIM_SQL
    assert "CAST(:only_interactive AS integer) = 1" in REAL_CLAIM_SQL


def test_operator_confirmed_payload_is_truthy() -> None:
    assert _is_operator_confirmed({"operator_confirmed": True}) is True
    assert _is_operator_confirmed({"operator_confirmed": "true"}) is True
    assert _is_operator_confirmed({"operator_confirmed": False}) is False
