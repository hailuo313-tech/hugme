from pathlib import Path

from services.app_download_conversion import (
    APP_DOWNLOAD_CATEGORIES,
    _FunnelState,
    _choose_category,
    _conversation_mode,
    _relationship_stage,
    _reply_language,
    _render_script,
)


ROOT = Path(__file__).resolve().parents[1]


def test_app_download_migration_seeds_explicit_funnel_categories() -> None:
    sql = (ROOT / "db" / "migration" / "V12__app_download_conversion_scripts.sql").read_text(
        encoding="utf-8"
    )

    for category in APP_DOWNLOAD_CATEGORIES:
        assert category in sql
    assert "{{app_download_url}}" in sql
    assert "app_download_conversion" in sql
    assert "ON CONFLICT (id) DO UPDATE" in sql


def test_selector_uses_clicked_not_downloaded_followup_after_delay() -> None:
    category, intent, scene_step = _choose_category(
        user_text="you make me so horny",
        state=_FunnelState(
            tracking_id="trk_1",
            minutes_since_link=3.5,
            clicked=True,
            downloaded=False,
        ),
        assistant_reply_count=5,
        user_level="B",
    )

    assert category == "app_link_clicked_followup"
    assert intent == "app_link_clicked_followup"
    assert scene_step == "clicked_not_downloaded"


def test_selector_does_not_push_download_for_serious_question() -> None:
    category, intent, scene_step = _choose_category(
        user_text="Can you have a serious conversation?",
        state=_FunnelState(
            tracking_id="trk_1",
            minutes_since_link=5.0,
            clicked=True,
            downloaded=False,
        ),
        assistant_reply_count=6,
        user_level="C",
    )

    assert category is None
    assert intent == "serious_chat"
    assert scene_step == "conversation"


def test_selector_does_not_push_download_for_preference_statement() -> None:
    category, intent, scene_step = _choose_category(
        user_text="I like women over 30 - the curvy type.",
        state=_FunnelState(
            tracking_id="trk_1",
            minutes_since_link=5.0,
            clicked=True,
            downloaded=False,
        ),
        assistant_reply_count=6,
        user_level="C",
    )

    assert category is None
    assert intent == "preference_chat"
    assert scene_step == "conversation"


def test_selector_does_not_resend_recent_unclicked_link() -> None:
    category, _, _ = _choose_category(
        user_text="continue",
        state=_FunnelState(
            tracking_id="trk_1",
            minutes_since_link=2.0,
            clicked=False,
        ),
        assistant_reply_count=5,
        user_level="B",
    )

    assert category is None


def test_selector_stops_after_download_handoff() -> None:
    category, intent, scene_step = _choose_category(
        user_text="done",
        state=_FunnelState(
            tracking_id="trk_1",
            minutes_since_link=8.0,
            clicked=True,
            downloaded=True,
            registered=False,
            paid=False,
        ),
        assistant_reply_count=5,
        user_level="A",
    )

    assert category is None
    assert intent == "third_party_handoff"
    assert scene_step == "download_complete"


def test_selector_promotes_direct_link_questions() -> None:
    category, intent, scene_step = _choose_category(
        user_text="send me the app link",
        state=_FunnelState(),
        assistant_reply_count=0,
        user_level="C",
    )

    assert category == "app_download_direct_cta"
    assert intent == "app_download_direct_cta"
    assert scene_step == "pre_click"


def test_conversation_mode_classifies_dual_mode_inputs() -> None:
    assert _conversation_mode("Can you have a serious conversation?") == "serious"
    assert _conversation_mode("I like women over 30 - the curvy type") == "preference"
    assert _conversation_mode("you make me so horny") == "flirty"
    assert _conversation_mode("how was your day?") == "neutral"


def test_render_script_replaces_app_download_url() -> None:
    assert (
        _render_script("Open here: {{app_download_url}}", app_download_url="https://app.example/dl")
        == "Open here: https://app.example/dl"
    )


def test_profile_helpers_allow_missing_profile_for_download_cta() -> None:
    assert _relationship_stage(None) == "S0"
    assert _reply_language(None, "where can i talk to you more privately?") == "en"
