from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_p4_11_media_cache_manager_contract_is_present():
    text = _read("admin/lib/mediaCache.ts")

    assert "class MediaCacheManager" in text
    assert "indexedDB.open" in text
    assert "cacheMedia(" in text
    assert "getCachedMedia(" in text
    assert "clearExpiredCache(" in text
    assert "getOfflineAvailableMedia(" in text
    assert "maxCacheSize = 500 * 1024 * 1024" in text
    assert "defaultExpiration = 7 * 24 * 60 * 60 * 1000" in text


def test_p4_11_media_history_tracks_cached_playback():
    text = _read("admin/lib/mediaHistory.ts")

    assert "class MediaHistoryManager" in text
    assert "eris_media_history" in text
    assert "maxHistoryItems = 50" in text
    assert "updatePlaybackPosition(" in text
    assert "getOfflineAvailableHistory(" in text
    assert "cachedOnly" in text


def test_p4_11_video_player_uses_cache_history_and_weak_network_preload():
    text = _read("admin/components/media/VideoPlayer.tsx")

    assert "mediaCacheManager.cacheMedia" in text
    assert "mediaCacheManager.getCachedMedia" in text
    assert "mediaCacheManager.preloadMedia" in text
    assert "mediaHistoryManager.updatePlaybackPosition" in text
    assert "useNetworkStatus" in text
    assert "isSlowConnection" in text
    assert "URL.createObjectURL" in text


def test_p4_11_documentation_points_to_pytest_contract():
    text = _read("docs/P4-11_MEDIA_RENDERING_CACHE.md")

    assert "admin/lib/mediaCache.ts" in text
    assert "admin/lib/mediaHistory.ts" in text
    assert "admin/components/media/VideoPlayer.tsx" in text
