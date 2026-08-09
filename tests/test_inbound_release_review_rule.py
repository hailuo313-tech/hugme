from types import SimpleNamespace
from unittest.mock import patch

from services.call_broadcast.incoming_listener import _incoming_call_event_key
from services.post_inbound_video_expert_gate import post_inbound_video_release_review_calls


def test_release_review_threshold_is_six():
    with patch(
        "services.post_inbound_video_expert_gate.settings.POST_INBOUND_VIDEO_RELEASE_REVIEW_CALLS",
        6,
    ):
        assert post_inbound_video_release_review_calls() == 6


def test_telegram_call_id_is_stable_deduplication_key():
    first_callback = SimpleNamespace(call_id=998877)
    retry_callback = SimpleNamespace(call_id=998877)
    next_call = SimpleNamespace(call_id=998878)

    assert _incoming_call_event_key(first_callback) == _incoming_call_event_key(retry_callback)
    assert _incoming_call_event_key(first_callback) != _incoming_call_event_key(next_call)
