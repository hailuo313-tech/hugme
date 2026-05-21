from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_admin_root_is_home_dashboard() -> None:
    page = read("admin/app/page.tsx")

    assert '<h1 className="mb-2 text-2xl font-semibold">总后台</h1>' in page
    assert 'href="/admin/conversations"' in page
    assert 'href="/admin/operator-dashboard"' in page
    assert 'title: "会话总览"' in page


def test_conversation_overview_has_dedicated_route() -> None:
    page = read("admin/app/conversations/page.tsx")

    assert "会话总览" in page
    assert 'href="/admin"' in page
    assert "/admin/conversations?" in page


def test_operator_dashboard_links_to_conversation_route() -> None:
    page = read("admin/app/operator-dashboard/page.tsx")

    assert 'href="/admin/conversations"' in page
    assert "`/admin/conversations?conversation_id=${selectedTask.conversation_id}`" in page
    assert "`/admin/?conversation_id=${selectedTask.conversation_id}`" not in page


def test_login_entry_returns_to_admin_home() -> None:
    auth = read("admin/lib/auth.ts")

    assert "export const DEFAULT_ADMIN_ENTRY_PATH = ADMIN_BASE_PATH;" in auth
