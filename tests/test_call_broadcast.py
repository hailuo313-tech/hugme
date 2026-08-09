"""Tests for Telethon + PyTgCalls call broadcast module (opt-in)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from services.call_broadcast.keywords import (
    is_immediate_video_call_code,
    is_video_call_request,
    matched_video_call_keyword,
)
from services.call_broadcast.triggers import maybe_enqueue_call_broadcast


def test_is_video_call_request_detects_common_phrases() -> None:
    assert is_video_call_request("can we do a video call tonight?")
    assert is_video_call_request("facetime me")
    assert is_video_call_request("我们视频通话吧")
    assert is_video_call_request("video")
    assert is_video_call_request("cam2")
    assert not is_video_call_request("send me a photo")
    assert not is_video_call_request("download the app")


def test_matched_video_call_keyword_returns_token() -> None:
    assert matched_video_call_keyword("let's facetime") == "facetime"
    assert matched_video_call_keyword("hello") is None


def test_test_code_8866_triggers_exact_match_only() -> None:
    assert is_immediate_video_call_code("8866")
    assert is_video_call_request("8866")
    assert matched_video_call_keyword("8866") == "8866"
    assert not is_video_call_request("18866")
    assert not is_video_call_request("8866 extra")


@pytest.mark.asyncio
async def test_maybe_enqueue_skips_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.call_broadcast.triggers.settings.CALL_BROADCAST_ENABLED",
        False,
        raising=False,
    )
    result = await maybe_enqueue_call_broadcast(
        user_id="u1",
        external_user_id="tg1",
        conversation_id="c1",
        chat_id=123,
        account_id="acc",
        user_text="video call me",
        trace_id="t1",
    )
    assert result == 0


@pytest.mark.asyncio
async def test_maybe_enqueue_skips_non_call_text(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.call_broadcast.triggers.settings.CALL_BROADCAST_ENABLED",
        True,
        raising=False,
    )
    result = await maybe_enqueue_call_broadcast(
        user_id="u1",
        external_user_id="tg1",
        conversation_id="c1",
        chat_id=123,
        account_id="acc",
        user_text="send nudes",
        trace_id="t1",
    )
    assert result == 0


@pytest.mark.asyncio
async def test_maybe_enqueue_routes_video_call_to_operator_handoff(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.call_broadcast.triggers.settings.CALL_BROADCAST_ENABLED",
        True,
        raising=False,
    )

    result = await maybe_enqueue_call_broadcast(
        user_id="u1",
        external_user_id="tg1",
        conversation_id="c1",
        chat_id=123,
        account_id="acc",
        user_text="video call me now",
        trace_id="t1",
    )
    assert result == 0


@pytest.mark.asyncio
async def test_maybe_enqueue_routes_8866_to_operator_handoff(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.call_broadcast.triggers.settings.CALL_BROADCAST_ENABLED",
        True,
        raising=False,
    )

    result = await maybe_enqueue_call_broadcast(
        user_id="u1",
        external_user_id="tg1",
        conversation_id="c1",
        chat_id=123,
        account_id="acc",
        user_text="8866",
        trace_id="t1",
    )
    assert result == 0


class _Ctx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_run_call_broadcast_uses_pytgcalls(monkeypatch) -> None:
    from uuid import uuid4

    from services.call_broadcast import session as call_session

    fake_pytgcalls = MagicMock()
    fake_pytgcalls.play = AsyncMock()
    monkeypatch.setattr(
        call_session,
        "ensure_playable_video",
        AsyncMock(return_value="/tmp/demo.mp4"),
    )
    monkeypatch.setattr(
        call_session,
        "probe_video_duration_seconds",
        AsyncMock(return_value=10.5),
    )
    monkeypatch.setattr(
        call_session,
        "get_pytgcalls",
        AsyncMock(return_value=fake_pytgcalls),
    )
    monkeypatch.setattr(
        call_session.telegram_account_manager,
        "get_client",
        AsyncMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(call_session, "_cache_call_peer", AsyncMock())
    stop_mock = AsyncMock()
    monkeypatch.setattr(call_session, "_stop_stream", stop_mock)
    sleep_mock = AsyncMock()
    monkeypatch.setattr(call_session.asyncio, "sleep", sleep_mock)

    playback = await call_session.run_call_broadcast(
        account_id=uuid4(),
        chat_id=999,
        video_path="/data/videos/demo.mp4",
        duration_seconds=30,
        trace_id="trace",
        prepared=call_session.CallPlaybackPrepare("/tmp/demo.mp4", 10.5, 10.5),
    )
    assert playback.playback_seconds == 10.5
    assert playback.probed_seconds == 10.5
    assert fake_pytgcalls.play.await_count == 2
    connect_args = fake_pytgcalls.play.await_args_list[0].args
    assert connect_args[0] == 999
    assert connect_args[1] is None
    play_args = fake_pytgcalls.play.await_args_list[1].args
    assert play_args[0] == 999
    assert play_args[1] == "/tmp/demo.mp4"
    assert [call.args[0] for call in sleep_mock.await_args_list] == [3.0, 10.5]
    stop_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_call_broadcast_waits_for_answer_before_playback(monkeypatch) -> None:
    from uuid import uuid4

    from services.call_broadcast import session as call_session

    fake_pytgcalls = MagicMock()
    answer_event = asyncio.Event()
    sleep_started = asyncio.Event()
    play_started = asyncio.Event()

    async def _delayed_connect(_chat_id: int, path: str | None, _config: object = None) -> None:
        play_started.set()
        if path is None:
            await answer_event.wait()

    fake_pytgcalls.play = _delayed_connect
    monkeypatch.setattr(
        call_session,
        "ensure_playable_video",
        AsyncMock(return_value="/tmp/demo.mp4"),
    )
    monkeypatch.setattr(
        call_session,
        "probe_video_duration_seconds",
        AsyncMock(return_value=8.0),
    )
    monkeypatch.setattr(
        call_session,
        "get_pytgcalls",
        AsyncMock(return_value=fake_pytgcalls),
    )
    monkeypatch.setattr(
        call_session.telegram_account_manager,
        "get_client",
        AsyncMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(call_session, "_cache_call_peer", AsyncMock())
    stop_mock = AsyncMock()
    monkeypatch.setattr(call_session, "_stop_stream", stop_mock)

    real_sleep = asyncio.sleep

    async def _tracked_sleep(seconds: float) -> None:
        sleep_started.set()
        await real_sleep(seconds)

    monkeypatch.setattr(call_session.asyncio, "sleep", _tracked_sleep)

    task = asyncio.create_task(
        call_session.run_call_broadcast(
            account_id=uuid4(),
            chat_id=999,
            video_path="/data/videos/demo.mp4",
            duration_seconds=30,
            trace_id="trace",
            prepared=call_session.CallPlaybackPrepare("/tmp/demo.mp4", 8.0, 8.0),
        )
    )
    await asyncio.wait_for(play_started.wait(), timeout=2)
    assert not sleep_started.is_set()

    answer_event.set()
    playback = await asyncio.wait_for(task, timeout=12)
    assert playback.playback_seconds == 8.0
    assert sleep_started.is_set()
    stop_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_call_broadcast_classifies_play_timeout_as_unanswered(monkeypatch) -> None:
    from uuid import uuid4

    from services.call_broadcast import session as call_session

    fake_pytgcalls = MagicMock()
    fake_pytgcalls.play = AsyncMock(side_effect=asyncio.TimeoutError())
    monkeypatch.setattr(
        call_session,
        "ensure_playable_video",
        AsyncMock(return_value="/tmp/demo.mp4"),
    )
    monkeypatch.setattr(
        call_session,
        "probe_video_duration_seconds",
        AsyncMock(return_value=8.0),
    )
    monkeypatch.setattr(
        call_session,
        "get_pytgcalls",
        AsyncMock(return_value=fake_pytgcalls),
    )
    monkeypatch.setattr(
        call_session.telegram_account_manager,
        "get_client",
        AsyncMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(call_session, "_cache_call_peer", AsyncMock())
    stop_mock = AsyncMock()
    monkeypatch.setattr(call_session, "_stop_stream", stop_mock)
    sleep_mock = AsyncMock()
    monkeypatch.setattr(call_session.asyncio, "sleep", sleep_mock)

    with pytest.raises(call_session.CallBroadcastStreamError, match="call not answered"):
        await call_session.run_call_broadcast(
            account_id=uuid4(),
            chat_id=999,
            video_path="/data/videos/demo.mp4",
            duration_seconds=30,
            trace_id="trace",
            prepared=call_session.CallPlaybackPrepare("/tmp/demo.mp4", 8.0, 8.0),
        )

    sleep_mock.assert_not_awaited()
    stop_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_call_broadcast_uses_incoming_wrapper(monkeypatch) -> None:
    from uuid import uuid4

    from services.call_broadcast import session as call_session

    incoming_wrapper = MagicMock()
    incoming_wrapper.play = AsyncMock()
    manager_wrapper = MagicMock()
    monkeypatch.setattr(
        call_session,
        "prepare_call_broadcast_playback",
        AsyncMock(
            return_value=call_session.CallPlaybackPrepare(
                playable_path="/tmp/demo.mp4",
                playback_seconds=0.0,
                probed_seconds=0.0,
            )
        ),
    )
    manager_get = AsyncMock(return_value=manager_wrapper)
    monkeypatch.setattr(call_session, "get_pytgcalls", manager_get)
    monkeypatch.setattr(
        call_session.telegram_account_manager,
        "get_client",
        AsyncMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(call_session, "_cache_call_peer", AsyncMock())
    monkeypatch.setattr(call_session, "_stop_stream", AsyncMock())

        await call_session.run_call_broadcast(
        account_id=uuid4(),
        chat_id=999,
        video_path="/data/videos/demo.mp4",
        duration_seconds=1,
        pytgcalls=incoming_wrapper,
    )

    assert incoming_wrapper.play.await_count == 2
    assert incoming_wrapper.play.await_args_list[0].args[1] is None
    assert incoming_wrapper.play.await_args_list[1].args[1] == "/tmp/demo.mp4"
    manager_get.assert_not_awaited()


def test_display_playback_seconds_ceil_partial_second() -> None:
    from services.call_broadcast.duration import display_playback_seconds

    assert display_playback_seconds(15.371) == 16
    assert display_playback_seconds(39.009) == 40
    assert display_playback_seconds(15) == 15


def test_resolve_playback_duration_prefers_probed_length() -> None:
    from services.call_broadcast.ffmpeg_pipeline import resolve_playback_duration_seconds

    assert resolve_playback_duration_seconds(probed_seconds=12.4, configured_seconds=30) == 12.4
    assert resolve_playback_duration_seconds(probed_seconds=None, configured_seconds=45) == 45.0
    assert resolve_playback_duration_seconds(probed_seconds=None, configured_seconds=None, default_seconds=30) == 30.0


def test_resolve_call_broadcast_wall_timeout_scales_with_playback(monkeypatch) -> None:
    from services.call_broadcast import session as call_session

    monkeypatch.setattr(call_session.settings, "CALL_BROADCAST_INCOMING_WALL_TIMEOUT_SECONDS", 0, raising=False)
    monkeypatch.setattr(call_session.settings, "CALL_BROADCAST_ANSWER_TIMEOUT_SECONDS", 60, raising=False)
    monkeypatch.setattr(call_session.settings, "CALL_BROADCAST_PLAYBACK_TIMEOUT_BUFFER_SECONDS", 90, raising=False)
    monkeypatch.setattr(call_session.settings, "CALL_BROADCAST_DIAL_TEARDOWN_BUFFER_SECONDS", 45, raising=False)
    monkeypatch.setattr(call_session.settings, "CALL_BROADCAST_STALE_ACTIVE_MIN_SECONDS", 300, raising=False)

    short = call_session.resolve_call_broadcast_wall_timeout_seconds(30)
    long = call_session.resolve_call_broadcast_wall_timeout_seconds(120)
    assert short == 225.0
    assert long == 315.0
    assert long > short


def test_resolve_call_broadcast_wall_timeout_ignores_legacy_240_cap_by_default(monkeypatch) -> None:
    from services.call_broadcast import session as call_session

    monkeypatch.setattr(call_session.settings, "CALL_BROADCAST_INCOMING_WALL_TIMEOUT_SECONDS", 0, raising=False)
    wall = call_session.resolve_call_broadcast_wall_timeout_seconds(120)
    assert wall > 240.0


def test_resolve_stale_active_slack_matches_wall_budget(monkeypatch) -> None:
    from services.call_broadcast import session as call_session

    monkeypatch.setattr(call_session.settings, "CALL_BROADCAST_ANSWER_TIMEOUT_SECONDS", 60, raising=False)
    monkeypatch.setattr(call_session.settings, "CALL_BROADCAST_PLAYBACK_TIMEOUT_BUFFER_SECONDS", 90, raising=False)
    monkeypatch.setattr(call_session.settings, "CALL_BROADCAST_DIAL_TEARDOWN_BUFFER_SECONDS", 45, raising=False)

    assert call_session.resolve_stale_active_slack_seconds() == 225


@pytest.mark.asyncio
async def test_prepare_call_broadcast_playback_returns_playable(monkeypatch) -> None:
    from services.call_broadcast import session as call_session
    from services.call_broadcast.session import CallPlaybackPrepare

    monkeypatch.setattr(
        call_session,
        "_prepare_playback_sync",
        lambda **kwargs: CallPlaybackPrepare(
            playable_path="/tmp/ready.mp4",
            playback_seconds=42.0,
            probed_seconds=42.0,
        ),
    )

    prepared = await call_session.prepare_call_broadcast_playback(
        video_path="/data/videos/raw.mp4",
        duration_seconds=30,
        trace_id="t1",
    )
    assert prepared.playable_path == "/tmp/ready.mp4"
    assert prepared.playback_seconds == 42.0
    assert prepared.probed_seconds == 42.0


@pytest.mark.asyncio
async def test_peek_playback_prepare_returns_warmed_entry(monkeypatch) -> None:
    from services.call_broadcast import session as call_session
    from services.call_broadcast.session import CallPlaybackPrepare

    call_session.clear_playback_prepare_cache()
    monkeypatch.setattr(
        call_session,
        "_prepare_playback_sync",
        lambda **kwargs: CallPlaybackPrepare(
            playable_path="/tmp/ready.mp4",
            playback_seconds=12.0,
            probed_seconds=12.0,
        ),
    )
    await call_session.prepare_call_broadcast_playback(
        video_path="/data/videos/raw.mp4",
        duration_seconds=30,
    )
    peeked = call_session.peek_playback_prepare(
        video_path="/data/videos/raw.mp4",
        duration_seconds=30,
    )
    assert peeked is not None
    assert peeked.playable_path == "/tmp/ready.mp4"
    call_session.clear_playback_prepare_cache()


def test_resolve_call_broadcast_work_dir_prefers_persistent_cache(monkeypatch) -> None:
    from services.call_broadcast import session as call_session

    monkeypatch.setattr(call_session.settings, "CALL_BROADCAST_WORK_DIR", "/tmp/call_broadcast", raising=False)
    monkeypatch.setattr(call_session.settings, "CALL_BROADCAST_VIDEO_ROOT", "/data/videos", raising=False)
    assert call_session.resolve_call_broadcast_work_dir() == "/data/videos/.call_broadcast_cache"


@pytest.mark.asyncio
async def test_prepare_call_broadcast_playback_uses_memory_cache(monkeypatch) -> None:
    from services.call_broadcast import session as call_session
    from services.call_broadcast.session import CallPlaybackPrepare

    call_session.clear_playback_prepare_cache()
    prepare_sync = Mock(
        return_value=CallPlaybackPrepare(
            playable_path="/tmp/ready.mp4",
            playback_seconds=12.0,
            probed_seconds=12.0,
        )
    )
    monkeypatch.setattr(call_session, "_prepare_playback_sync", prepare_sync)

    first = await call_session.prepare_call_broadcast_playback(
        video_path="/data/videos/raw.mp4",
        duration_seconds=30,
    )
    second = await call_session.prepare_call_broadcast_playback(
        video_path="/data/videos/raw.mp4",
        duration_seconds=30,
    )
    assert first == second
    assert prepare_sync.call_count == 1
    call_session.clear_playback_prepare_cache()


@pytest.mark.asyncio
async def test_probe_video_duration_seconds_parses_ffprobe_output(tmp_path) -> None:
    from services.call_broadcast.ffmpeg_pipeline import probe_video_duration_seconds

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")

    with patch(
        "services.call_broadcast.ffmpeg_pipeline.shutil.which",
        return_value="/usr/bin/ffprobe",
    ), patch(
        "services.call_broadcast.ffmpeg_pipeline.subprocess.run",
        return_value=Mock(returncode=0, stdout=b"18.75\n", stderr=b""),
    ):
        duration = await probe_video_duration_seconds(str(video))

    assert duration == 18.75


@pytest.mark.asyncio
async def test_worker_disabled_by_default(monkeypatch) -> None:
    from services.call_broadcast.worker import run_one_tick

    monkeypatch.setattr(
        "services.call_broadcast.worker.settings.CALL_BROADCAST_ENABLED",
        False,
        raising=False,
    )
    stats = await run_one_tick()
    assert stats == {"enabled": False}


def test_spawn_helper_noop_when_disabled(monkeypatch) -> None:
    from services.mtproto.auto_reply import _spawn_call_broadcast_enqueue

    monkeypatch.setattr(
        "services.mtproto.auto_reply.settings.CALL_BROADCAST_ENABLED",
        False,
        raising=False,
    )
    create_task = MagicMock()
    monkeypatch.setattr("services.mtproto.auto_reply.asyncio.create_task", create_task)
    _spawn_call_broadcast_enqueue(
        user_id="u1",
        external_user_id="e1",
        conversation_id="c1",
        chat_id=1,
        account_id="a1",
        user_text="video call",
        trace_id="t1",
    )
    create_task.assert_not_called()


def test_spawn_helper_schedules_task_when_enabled(monkeypatch) -> None:
    from services.mtproto.auto_reply import _spawn_call_broadcast_enqueue

    monkeypatch.setattr(
        "services.mtproto.auto_reply.settings.CALL_BROADCAST_ENABLED",
        True,
        raising=False,
    )
    create_task = MagicMock()
    monkeypatch.setattr("services.mtproto.auto_reply.asyncio.create_task", create_task)
    _spawn_call_broadcast_enqueue(
        user_id="u1",
        external_user_id="e1",
        conversation_id="c1",
        chat_id=1,
        account_id="a1",
        user_text="video call",
        trace_id="t1",
    )
    create_task.assert_called_once()


def test_extract_incoming_peer_from_chat_id() -> None:
    from services.call_broadcast.incoming_listener import _extract_incoming_peer

    class _Update:
        chat_id = 12345
        access_hash = 999

    chat_id, access_hash = _extract_incoming_peer(_Update())
    assert chat_id == 12345
    assert access_hash == 999


def test_extract_incoming_peer_from_nested_chat() -> None:
    from services.call_broadcast.incoming_listener import _extract_incoming_peer

    class _Chat:
        id = 777
        access_hash = 888

    class _Update:
        chat = _Chat()

    chat_id, access_hash = _extract_incoming_peer(_Update())
    assert chat_id == 777
    assert access_hash == 888


@pytest.mark.asyncio
async def test_incoming_listener_start_skipped_when_disabled(monkeypatch) -> None:
    from services.call_broadcast import incoming_listener

    monkeypatch.setattr(incoming_listener.settings, "CALL_BROADCAST_ENABLED", False, raising=False)
    monkeypatch.setattr(
        incoming_listener.settings,
        "CALL_BROADCAST_INCOMING_AUTO_ANSWER",
        False,
        raising=False,
    )
    register = AsyncMock()
    monkeypatch.setattr(incoming_listener, "_register_all_active_accounts", register)

    await incoming_listener.start_incoming_call_listeners()
    register.assert_not_awaited()


@pytest.mark.asyncio
async def test_incoming_listener_registers_when_enabled(monkeypatch) -> None:
    from services.call_broadcast import incoming_listener

    monkeypatch.setattr(incoming_listener.settings, "CALL_BROADCAST_ENABLED", True, raising=False)
    monkeypatch.setattr(
        incoming_listener.settings,
        "CALL_BROADCAST_INCOMING_AUTO_ANSWER",
        True,
        raising=False,
    )
    monkeypatch.setattr(incoming_listener, "pytgcalls_import_error", lambda: None)
    monkeypatch.setattr(
        incoming_listener,
        "_register_all_active_accounts",
        AsyncMock(return_value=2),
    )
    monkeypatch.setattr(incoming_listener.asyncio, "create_task", MagicMock())

    await incoming_listener.start_incoming_call_listeners()
    assert incoming_listener._running is True


@pytest.mark.asyncio
async def test_handle_incoming_skips_when_busy(monkeypatch) -> None:
    from uuid import uuid4

    from services.call_broadcast import incoming_listener

    account_id = str(uuid4())
    monkeypatch.setattr(incoming_listener.settings, "CALL_BROADCAST_ENABLED", True, raising=False)
    monkeypatch.setattr(
        incoming_listener.settings,
        "CALL_BROADCAST_INCOMING_AUTO_ANSWER",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        incoming_listener.settings,
        "CALL_BROADCAST_MAX_CONCURRENT_PER_ACCOUNT",
        1,
        raising=False,
    )

    class _Update:
        chat_id = 555

    monkeypatch.setattr(
        incoming_listener,
        "count_active_calls_for_account",
        AsyncMock(return_value=1),
    )
    run = AsyncMock()
    monkeypatch.setattr(incoming_listener, "run_call_broadcast", run)

    await incoming_listener._handle_incoming_call(account_id, _Update())
    run.assert_not_awaited()
    assert (account_id, 555) not in incoming_listener._inflight_calls


@pytest.mark.asyncio
async def test_handle_incoming_not_busy_on_first_call(monkeypatch) -> None:
    from uuid import uuid4

    from services.call_broadcast import incoming_listener

    account_id = str(uuid4())
    monkeypatch.setattr(incoming_listener.settings, "CALL_BROADCAST_ENABLED", True, raising=False)
    monkeypatch.setattr(
        incoming_listener.settings,
        "CALL_BROADCAST_INCOMING_AUTO_ANSWER",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        incoming_listener,
        "count_active_calls_for_account",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        incoming_listener,
        "count_completed_inbound_calls_for_chat",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        incoming_listener,
        "count_prior_inbound_call_attempts",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        incoming_listener,
        "resolve_inbound_sequence_video_asset",
        AsyncMock(
            return_value={
                "id": str(uuid4()),
                "file_path": "/data/videos/demo.mp4",
                "duration_seconds": 9,
                "inbound_call_number": 1,
                "resolved_play_sequence": 1,
            }
        ),
    )
    monkeypatch.setattr(
        incoming_listener,
        "create_inbound_auto_answer_job",
        AsyncMock(return_value=str(uuid4())),
    )
    monkeypatch.setattr(incoming_listener, "mark_job_streaming", AsyncMock())
    monkeypatch.setattr(incoming_listener, "finalize_job", AsyncMock())
    from services.call_broadcast.session import CallPlaybackPrepare

    monkeypatch.setattr(
        incoming_listener,
        "prepare_call_broadcast_playback",
        AsyncMock(
            return_value=CallPlaybackPrepare(
                playable_path="/tmp/demo.mp4",
                playback_seconds=9.0,
                probed_seconds=9.0,
            )
        ),
    )
    run = AsyncMock()
    monkeypatch.setattr(incoming_listener, "run_call_broadcast", run)

    class _FakeSession:
        async def commit(self):
            return None

    class _FakeCtx:
        async def __aenter__(self):
            return _FakeSession()

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(incoming_listener, "AsyncSessionLocal", lambda: _FakeCtx())

    class _Update:
        chat_id = 555

    await incoming_listener._handle_incoming_call(account_id, _Update())
    run.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_inbound_sequence_first_call(monkeypatch) -> None:
    from services.call_broadcast import jobs as cb_jobs

    monkeypatch.setattr(
        cb_jobs,
        "count_completed_inbound_calls_for_chat",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        cb_jobs,
        "resolve_video_asset_by_play_sequence",
        AsyncMock(
            side_effect=lambda _db, seq: {
                "id": f"v{seq}",
                "title": f"video{seq}",
                "file_path": f"/data/v{seq}.mp4",
                "play_sequence": seq,
            }
            if seq == 1
            else None
        ),
    )

    class _Db:
        pass

    asset = await cb_jobs.resolve_inbound_sequence_video_asset(_Db(), 12345)
    assert asset is not None
    assert asset["resolved_play_sequence"] == 1
    assert asset["inbound_call_number"] == 1
    assert asset["file_path"] == "/data/v1.mp4"


@pytest.mark.asyncio
async def test_resolve_inbound_sequence_second_call_returns_none(monkeypatch) -> None:
    from services.call_broadcast import jobs as cb_jobs

    monkeypatch.setattr(
        cb_jobs,
        "count_completed_inbound_calls_for_chat",
        AsyncMock(return_value=1),
    )
    monkeypatch.setattr(
        cb_jobs,
        "resolve_video_asset_by_play_sequence",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        cb_jobs,
        "resolve_default_video_asset",
        AsyncMock(return_value=None),
    )

    asset = await cb_jobs.resolve_inbound_sequence_video_asset(object(), 99)
    assert asset is None


def test_inbound_call_requires_operator_review_after_two_auto_answers() -> None:
    from services.call_broadcast.incoming_review import inbound_call_requires_operator_review

    assert inbound_call_requires_operator_review(
        completed_playbacks=0,
        recorded_attempts=0,
    ) is False  # 1st call: auto
    assert inbound_call_requires_operator_review(
        completed_playbacks=1,
        recorded_attempts=1,
    ) is False  # 2nd call: auto
    assert inbound_call_requires_operator_review(
        completed_playbacks=2,
        recorded_attempts=2,
    ) is True   # 3rd+ call: manual


def test_failed_auto_answer_does_not_block_auto_retry() -> None:
    from services.call_broadcast.incoming_review import inbound_call_requires_operator_review

    assert inbound_call_requires_operator_review(
        completed_playbacks=0,
        recorded_attempts=1,
        operator_review_attempts=0,
    ) is False
    assert inbound_call_requires_operator_review(
        completed_playbacks=0,
        recorded_attempts=1,
        operator_review_attempts=1,
    ) is False


def test_fixed_reply_mode_keeps_two_auto_answers_even_if_global_threshold_changes(
    monkeypatch,
) -> None:
    from services.call_broadcast import incoming_listener

    monkeypatch.setattr(
        incoming_listener.settings,
        "CALL_BROADCAST_INBOUND_MANUAL_AFTER",
        1,
        raising=False,
    )

    assert incoming_listener._auto_answer_threshold_for_reply_mode("ai") == 1
    assert incoming_listener._auto_answer_threshold_for_reply_mode("fixed") == 2


def test_keyword_review_does_not_expire_while_pending() -> None:
    from datetime import datetime, timedelta, timezone

    from services.call_broadcast.incoming_review import _review_is_expired

    old = datetime.now(timezone.utc) - timedelta(hours=2)
    assert (
        _review_is_expired(trigger_source="inbound_keyword_review", created_at=old)
        is False
    )
    assert (
        _review_is_expired(trigger_source="inbound_operator_review", created_at=old)
        is True
    )


@pytest.mark.asyncio
async def test_accept_operator_review_blocks_when_account_busy(monkeypatch) -> None:
    from services.call_broadcast import incoming_review as review_mod

    job_id = "11111111-1111-1111-1111-111111111111"
    account_id = "22222222-2222-2222-2222-222222222222"

    async def _hydrate(*_args, **_kwargs):
        return review_mod.PendingIncomingReview(
            job_id=job_id,
            chat_id=5422465697,
            account_id=account_id,
            trace_id="trace",
            access_hash=123,
            inbound_call_number=1,
            expires_at=9999999999.0,
        )

    monkeypatch.setattr(review_mod, "hydrate_pending_review_from_job", _hydrate)
    monkeypatch.setattr(
        review_mod,
        "_load_operator_job",
        AsyncMock(
            return_value={
                "id": job_id,
                "chat_id": 5422465697,
                "account_id": account_id,
                "status": "pending_operator",
                "trace_id": "trace",
                "metadata": {},
            }
        ),
    )
    monkeypatch.setattr(review_mod, "count_active_calls_for_account", AsyncMock(return_value=1))

    result = await review_mod.accept_operator_review(
        job_id=job_id,
        video_asset_id="33333333-3333-3333-3333-333333333333",
        operator_id="op1",
    )
    assert result == {"ok": False, "reason": "account_busy_on_call"}


@pytest.mark.asyncio
async def test_resolve_inbound_sequence_third_call(monkeypatch) -> None:
    from services.call_broadcast import jobs as cb_jobs

    monkeypatch.setattr(
        cb_jobs,
        "count_completed_inbound_calls_for_chat",
        AsyncMock(return_value=2),
    )

    async def _by_seq(_db, seq):
        return {
            "id": f"v{seq}",
            "file_path": f"/data/v{seq}.mp4",
            "play_sequence": seq,
        }

    monkeypatch.setattr(cb_jobs, "resolve_video_asset_by_play_sequence", _by_seq)

    asset = await cb_jobs.resolve_inbound_sequence_video_asset(object(), 99)
    assert asset["inbound_call_number"] == 3
    assert asset["resolved_play_sequence"] == 3
    assert asset["file_path"] == "/data/v3.mp4"
