from inspect import getsource

from services.profile_intake import (
    OPERATOR_COUNTRY_SOURCE,
    PHONE_COUNTRY_SOURCE,
    apply_operator_country_correction,
    plan_country_write,
    write_country_code,
)


def test_operator_overrides_phone_locked_grading() -> None:
    plan = plan_country_write(
        incoming_code="US",
        incoming_source=OPERATOR_COUNTRY_SOURCE,
        existing_grading_code="PH",
        existing_grading_source=PHONE_COUNTRY_SOURCE,
        existing_stated_code="PH",
        existing_phone_country="PH",
    )
    assert plan.update_grading is True
    assert plan.grading_country_code == "US"
    assert plan.grading_source == OPERATOR_COUNTRY_SOURCE
    assert plan.stated_country_code is None
    assert plan.phone_country is None
    assert plan.mismatch is True


def test_phone_does_not_override_operator_grading() -> None:
    plan = plan_country_write(
        incoming_code="PH",
        incoming_source=PHONE_COUNTRY_SOURCE,
        existing_grading_code="US",
        existing_grading_source=OPERATOR_COUNTRY_SOURCE,
        existing_phone_country=None,
    )
    assert plan.update_grading is False
    assert plan.grading_country_code is None
    assert plan.phone_country == "PH"
    assert plan.mismatch is True


def test_stated_does_not_override_operator_grading() -> None:
    plan = plan_country_write(
        incoming_code="BR",
        incoming_source="chat_answer",
        existing_grading_code="US",
        existing_grading_source=OPERATOR_COUNTRY_SOURCE,
        existing_stated_code="PH",
        existing_phone_country="PH",
    )
    assert plan.update_grading is False
    assert plan.stated_country_code == "BR"
    assert plan.grading_country_code is None


def test_operator_correction_keeps_session_in_human_control() -> None:
    apply_src = getsource(apply_operator_country_correction)
    write_src = getsource(write_country_code)
    assert "WAITING_OPERATOR" not in apply_src
    assert "t1_country_manual_chat" not in apply_src
    assert "handoff" not in apply_src.lower()
    assert "WAITING_OPERATOR" not in write_src
    assert "country_corrected_by" in apply_src
    assert "OPERATOR_COUNTRY_SOURCE" in apply_src


def test_admin_country_routes_reuse_operator_reply() -> None:
    from api import admin as admin_api

    update_src = getsource(admin_api.admin_update_conversation_country)
    resend_src = getsource(admin_api.admin_resend_conversation_country_link)
    preview_src = getsource(admin_api.admin_preview_conversation_country_correction)
    assert "apply_operator_country_correction" in update_src
    assert "release_human_takeover_to_ai" in update_src
    assert "operator_country_not_t1" in update_src
    assert "admin_send_conversation_operator_reply" in resend_src
    assert "_conversation_country_preview" in preview_src