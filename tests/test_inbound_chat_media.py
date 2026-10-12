from __future__ import annotations

from types import SimpleNamespace

from services.mtproto import inbound_media


def test_find_chat_media_file_checks_inbound_and_operator(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(inbound_media.settings, "MEDIA_UPLOAD_DIR", str(tmp_path))
    message_id = "11111111-1111-1111-1111-111111111111"

    assert inbound_media.find_chat_media_file(message_id) is None

    photo_dir = tmp_path / "inbound-photos"
    photo_dir.mkdir()
    photo = photo_dir / f"{message_id}.jpg"
    photo.write_bytes(b"jpg")
    assert inbound_media.find_chat_media_file(message_id) == photo

    photo.unlink()
    video_dir = tmp_path / "inbound-videos"
    video_dir.mkdir()
    video = video_dir / f"{message_id}.mp4"
    video.write_bytes(b"mp4")
    assert inbound_media.find_chat_media_file(message_id) == video

    video.unlink()
    operator_dir = tmp_path / "operator-media"
    operator_dir.mkdir()
    outbound = operator_dir / f"{message_id}.png"
    outbound.write_bytes(b"png")
    assert inbound_media.find_chat_media_file(message_id) == outbound


def test_inbound_av_media_kind_detects_video_and_skips_sticker() -> None:
    assert inbound_media.inbound_av_media_kind(SimpleNamespace(video=object(), sticker=None)) == "video"
    assert inbound_media.inbound_av_media_kind(SimpleNamespace(voice=object(), sticker=None)) == "audio"
    assert inbound_media.inbound_av_media_kind(
        SimpleNamespace(
            sticker=object(),
            video=object(),
            document=SimpleNamespace(mime_type="video/mp4"),
        )
    ) is None
    assert inbound_media.inbound_av_media_kind(
        SimpleNamespace(
            sticker=None,
            video=None,
            voice=None,
            audio=None,
            document=SimpleNamespace(mime_type="video/mp4"),
            media=None,
        )
    ) == "video"
