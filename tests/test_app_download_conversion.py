from pathlib import Path
from types import SimpleNamespace

import pytest

import services.app_download_conversion as conversion
from services.app_download_conversion import (
    APP_DOWNLOAD_CATEGORIES,
    _FunnelState,
    _choose_category,
    _keyword_matches,
    _relationship_stage,
    _reply_language,
    _render_script,
    _split_asset_keywords,
    maybe_select_app_download_reply,
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
        user_text="hey",
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


def test_selector_resends_link_when_user_explicitly_asks_during_cooldown() -> None:
    category, intent, scene_step = _choose_category(
        user_text="Download APP LINK",
        state=_FunnelState(
            tracking_id="trk_1",
            minutes_since_link=2.0,
            clicked=False,
        ),
        assistant_reply_count=5,
        user_level="C",
    )

    assert category == "app_download_direct_cta"
    assert intent == "app_download_direct_cta"
    assert scene_step == "pre_click"


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


def test_render_script_replaces_app_download_url() -> None:
    assert (
        _render_script("Open here: {{app_download_url}}", app_download_url="https://app.example/dl")
        == "Open here: https://app.example/dl"
    )


def test_render_script_force_appends_missing_app_download_url() -> None:
    assert (
        _render_script("Open the app here.", app_download_url="https://app.example/dl", force_url=True)
        == "Open the app here.\nhttps://app.example/dl"
    )


def test_profile_helpers_allow_missing_profile_for_download_cta() -> None:
    assert _relationship_stage(None) == "S0"
    assert _reply_language(None, "where can i talk to you more privately?") == "en"


def test_reply_language_follows_user_message_language() -> None:
    assert _reply_language(None, "Hola, m\u00e1ndame el link") == "es"
    assert _reply_language(None, "Ol\u00e1, quero o app") == "pt"
    assert _reply_language(None, "\u3053\u3093\u306b\u3061\u306f\u3001\u30ea\u30f3\u30af\u3092\u9001\u3063\u3066") == "ja"
    assert _reply_language(None, "\uc548\ub155\ud558\uc138\uc694 \ub9c1\ud06c \ubcf4\ub0b4\uc918") == "ko"


def test_asset_keyword_split_accepts_operator_separators() -> None:
    assert _split_asset_keywords("video, vid\u3001clip\uff0ccustom video` tape") == [
        "video",
        "vid",
        "clip",
        "custom video",
        "tape",
    ]


def test_asset_keyword_requires_asset_request_intent() -> None:
    assert _keyword_matches(
        "can i see your mirror selfie",
        "mirror selfie",
        asset_kind="image",
    )
    assert _keyword_matches(
        "send me a bedroom video",
        "bedroom video",
        asset_kind="video",
    )
    assert _keyword_matches(
        "drop a short clip please",
        "short clip",
        asset_kind="video",
    )
    assert not _keyword_matches(
        "your nipples is very nice fuck shiet",
        "nipples",
        asset_kind="image",
    )
    assert not _keyword_matches(
        "you so sexy honey i love it",
        "sexy",
        asset_kind="video",
    )
    assert not _keyword_matches(
        "i play my cock already",
        "cock",
        asset_kind="video",
    )


@pytest.mark.asyncio
async def test_asset_keyword_template_selects_attached_media(monkeypatch) -> None:
    class Result:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class FakeDb:
        async def execute(self, sql, params=None):
            sql_text = str(sql)
            if "FROM script_templates" in sql_text:
                return Result(
                    [
                        SimpleNamespace(
                            _mapping={
                                "id": "33333333-3333-3333-3333-333333333333",
                                "category_key": "app_download_first_push",
                                "title": conversion.ASSET_KEYWORD_TRIGGER_TITLES[0],
                                "content": "video, vid, custom video",
                                "language": "en",
                                "platform": "telegram_real_user",
                                "user_level": None,
                                "persona_slug": None,
                                "hook": "reply",
                            }
                        )
                    ]
                )
            if "FROM script_template_assets" in sql_text:
                return Result(
                    [
                        SimpleNamespace(
                            _mapping={
                                "id": "asset-1",
                                "asset_type": "video",
                                "asset_url": "https://cdn.example/video.mp4",
                                "mime_type": "video/mp4",
                                "caption": None,
                                "sort_order": 0,
                            }
                        )
                    ]
                )
            return Result([])

    async def fake_resolve_app_download_url(_db):
        return "https://app.example/download"

    monkeypatch.setattr(conversion, "resolve_app_download_url", fake_resolve_app_download_url)
    monkeypatch.setattr(conversion.settings, "APP_DOWNLOAD_CONVERSION_ENABLED", True)

    decision = await maybe_select_app_download_reply(
        db=FakeDb(),
        user_id="11111111-1111-1111-1111-111111111111",
        conversation_id="22222222-2222-2222-2222-222222222222",
        user_text="send me a custom video",
        profile_row={"user_level": "C"},
        character_row=None,
        assistant_reply_count=0,
        trigger_message_id=None,
        trace_id="trace-asset",
        classified_intent=None,
    )

    assert decision is not None
    assert decision.intent == "asset_keyword_request"
    assert decision.script_hit_id == "33333333-3333-3333-3333-333333333333"
    assert conversion.ASSET_KEYWORD_APP_DOWNLOAD_COPY in decision.content
    assert "https://app.example/download" in decision.content
    assert "(Code: c5a8we)" in decision.content
    assert "everything is unlocked there" in decision.content
    assert decision.assets[0]["asset_url"] == "https://cdn.example/video.mp4"


@pytest.mark.asyncio
async def test_asset_keyword_template_combines_image_and_video_media(monkeypatch) -> None:
    class Result:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class FakeDb:
        async def execute(self, sql, params=None):
            sql_text = str(sql)
            if "FROM script_templates" in sql_text:
                return Result(
                    [
                        SimpleNamespace(
                            _mapping={
                                "id": "33333333-3333-3333-3333-333333333333",
                                "category_key": "app_download_first_push",
                                "title": conversion.ASSET_KEYWORD_TRIGGER_TITLES[0],
                                "content": "video, vid",
                                "language": "en",
                                "platform": "telegram_real_user",
                                "user_level": None,
                                "persona_slug": None,
                                "hook": "reply",
                            }
                        ),
                        SimpleNamespace(
                            _mapping={
                                "id": "44444444-4444-4444-4444-444444444444",
                                "category_key": "app_download_first_push",
                                "title": conversion.ASSET_KEYWORD_TRIGGER_TITLES[1],
                                "content": "photo, pic, picture",
                                "language": "en",
                                "platform": "telegram_real_user",
                                "user_level": None,
                                "persona_slug": None,
                                "hook": "reply",
                            }
                        ),
                    ]
                )
            if "FROM script_template_assets" in sql_text:
                if params["id"] == "33333333-3333-3333-3333-333333333333":
                    return Result(
                        [
                            SimpleNamespace(
                                _mapping={
                                    "id": "asset-video",
                                    "asset_type": "video",
                                    "asset_url": "https://cdn.example/video.mp4",
                                    "mime_type": "video/mp4",
                                    "caption": None,
                                    "sort_order": 0,
                                }
                            )
                        ]
                    )
                return Result(
                    [
                        SimpleNamespace(
                            _mapping={
                                "id": "asset-image",
                                "asset_type": "image",
                                "asset_url": "https://cdn.example/photo.jpg",
                                "mime_type": "image/jpeg",
                                "caption": None,
                                "sort_order": 0,
                            }
                        )
                    ]
                )
            return Result([])

    async def fake_resolve_app_download_url(_db):
        return "https://app.example/download"

    monkeypatch.setattr(conversion, "resolve_app_download_url", fake_resolve_app_download_url)
    monkeypatch.setattr(conversion.settings, "APP_DOWNLOAD_CONVERSION_ENABLED", True)

    decision = await maybe_select_app_download_reply(
        db=FakeDb(),
        user_id="11111111-1111-1111-1111-111111111111",
        conversation_id="22222222-2222-2222-2222-222222222222",
        user_text="send me a photo and video",
        profile_row={"user_level": "C"},
        character_row=None,
        assistant_reply_count=0,
        trigger_message_id=None,
        trace_id="trace-asset",
        classified_intent=None,
    )

    assert decision is not None
    assert [asset["asset_type"] for asset in decision.assets] == ["video", "image"]
    assert decision.scene_step == "asset_keyword:video,photo"
