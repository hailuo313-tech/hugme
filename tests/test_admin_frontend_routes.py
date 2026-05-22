from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_admin_root_is_current_home_dashboard() -> None:
    page = read("admin/app/page.tsx")

    assert '<h1 className="mb-2 text-2xl font-semibold">总后台</h1>' in page
    assert 'href="/admin/conversations"' in page
    assert 'href="/admin/telegram-accounts"' in page
    assert 'title: "会话总览"' in page
    assert 'title: "TG 账号"' in page
    assert 'title: "H5 聊天"' in page


def test_admin_home_no_longer_links_legacy_pages() -> None:
    page = read("admin/app/page.tsx")

    assert 'href="/admin/operator-dashboard"' not in page
    assert 'href="/admin/scripts"' not in page
    assert 'href="/admin/characters"' not in page
    assert 'href="/admin/memories"' not in page
    assert 'href="/admin/push"' not in page
    assert 'href="/admin/feedback"' not in page
    assert 'href="/admin/media"' not in page


def test_conversation_overview_has_dedicated_route() -> None:
    page = read("admin/app/conversations/page.tsx")

    assert "会话总览" in page
    assert 'href="/admin"' in page
    assert 'href="/admin/telegram-accounts"' in page
    assert "/admin/conversations?" in page


def test_legacy_admin_pages_are_removed() -> None:
    legacy_pages = [
        "admin/app/operator-dashboard/page.tsx",
        "admin/app/scripts/page.tsx",
        "admin/app/characters/page.tsx",
        "admin/app/memories/page.tsx",
        "admin/app/push/page.tsx",
        "admin/app/feedback/page.tsx",
        "admin/app/media/page.tsx",
    ]

    for path in legacy_pages:
        assert not (ROOT / path).exists()


def test_login_entry_returns_to_admin_home() -> None:
    auth = read("admin/lib/auth.ts")

    assert "export const DEFAULT_ADMIN_ENTRY_PATH = ADMIN_BASE_PATH;" in auth
    assert "function getBrowserStorage(): Storage | null" in auth
    assert "return getBrowserStorage()?.getItem(TOKEN_KEY) ?? null;" in auth
