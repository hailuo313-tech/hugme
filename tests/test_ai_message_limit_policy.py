from services import ai_message_limit


def test_system_message_sources_do_not_consume_realtime_ai_allowance() -> None:
    sql = ai_message_limit._NON_REALTIME_AI_MODEL_SQL
    assert "fixed_auto_reply" in sql
    assert "profile_intake" in sql
    assert "system_auto_reply" in sql
    assert "post_auto_answer_profile_prompt" in sql
    assert "post_video_script:%" in sql
    assert "auto_delivery_worker" in sql
    assert "post_release_ai_followup" in sql
    assert "script_asset" in sql


def test_unknown_country_limit_remains_twenty() -> None:
    assert ai_message_limit.NON_T1_AI_MESSAGE_LIMIT == 20


def test_t1_limit_is_six() -> None:
    assert ai_message_limit.T1_AI_MESSAGE_LIMIT == 6