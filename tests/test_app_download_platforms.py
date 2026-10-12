import pytest

from services.app_download_platforms import (
    APP_DOWNLOAD_PLATFORM_KEYS,
    normalize_app_download_platform,
    resolve_app_download_url,
)


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeDb:
    def __init__(
        self,
        *,
        conversation_account_id=None,
        account_platform=None,
        platform_urls=None,
        default_url=None,
    ):
        self.conversation_account_id = conversation_account_id
        self.account_platform = account_platform
        self.platform_urls = platform_urls or {}
        self.default_url = default_url

    async def execute(self, stmt, params=None):
        sql = str(stmt).lower()
        params = params or {}
        if "from messages" in sql:
            if self.conversation_account_id:
                return _Result((self.conversation_account_id,))
            return _Result(None)
        if "from telegram_accounts" in sql:
            return _Result((self.account_platform,))
        if "platform_key = :platform_key" in sql:
            url = self.platform_urls.get(params.get("platform_key"))
            if url:
                return _Result((url,))
            return _Result(None)
        if "from app_download_platforms" in sql:
            if self.default_url:
                return _Result((self.default_url,))
            return _Result(None)
        raise AssertionError(f"unexpected query: {stmt}")


def test_normalize_app_download_platform() -> None:
    assert normalize_app_download_platform("platform_c") == "platform_c"
    assert normalize_app_download_platform("PLATFORM_F") == "platform_f"
    assert normalize_app_download_platform("default") == "default"
    assert normalize_app_download_platform("") == "default"
    assert normalize_app_download_platform("platform_g") == "default"
    assert APP_DOWNLOAD_PLATFORM_KEYS[-1] == "platform_f"


@pytest.mark.asyncio
async def test_resolve_uses_bound_account_platform(monkeypatch) -> None:
    from services import app_download_platforms as platforms

    monkeypatch.setattr(platforms.settings, "APP_DOWNLOAD_URL", "https://env.example/app")
    db = _FakeDb(
        account_platform="platform_c",
        platform_urls={"platform_c": "https://c.example/app"},
        default_url="https://a.example/app",
    )

    url = await resolve_app_download_url(db, account_id="11111111-1111-1111-1111-111111111111")
    assert url == "https://c.example/app"


@pytest.mark.asyncio
async def test_resolve_falls_back_to_a_when_bound_platform_missing(monkeypatch) -> None:
    from services import app_download_platforms as platforms

    monkeypatch.setattr(platforms.settings, "APP_DOWNLOAD_URL", "https://env.example/app")
    db = _FakeDb(
        account_platform="platform_d",
        platform_urls={},
        default_url="https://a.example/app",
    )

    url = await resolve_app_download_url(db, account_id="11111111-1111-1111-1111-111111111111")
    assert url == "https://a.example/app"


@pytest.mark.asyncio
async def test_resolve_follow_default_prefers_a(monkeypatch) -> None:
    from services import app_download_platforms as platforms

    monkeypatch.setattr(platforms.settings, "APP_DOWNLOAD_URL", "https://env.example/app")
    db = _FakeDb(account_platform="default", default_url="https://a.example/app")

    url = await resolve_app_download_url(db, account_id="11111111-1111-1111-1111-111111111111")
    assert url == "https://a.example/app"


@pytest.mark.asyncio
async def test_resolve_uses_conversation_reception_account(monkeypatch) -> None:
    from services import app_download_platforms as platforms

    monkeypatch.setattr(platforms.settings, "APP_DOWNLOAD_URL", "https://env.example/app")
    db = _FakeDb(
        conversation_account_id="11111111-1111-1111-1111-111111111111",
        account_platform="platform_b",
        platform_urls={"platform_b": "https://b.example/app"},
        default_url="https://a.example/app",
    )

    url = await resolve_app_download_url(
        db,
        conversation_id="22222222-2222-2222-2222-222222222222",
    )
    assert url == "https://b.example/app"


@pytest.mark.asyncio
async def test_resolve_without_db_uses_env_fallback(monkeypatch) -> None:
    from services import app_download_platforms as platforms

    monkeypatch.setattr(platforms.settings, "APP_DOWNLOAD_URL", "https://env.example/app")
    url = await resolve_app_download_url(None)
    assert url == "https://env.example/app"
