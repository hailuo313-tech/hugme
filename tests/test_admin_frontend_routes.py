from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_admin_root_is_current_home_dashboard() -> None:
    page = read("admin/app/page.tsx")
    frame = read("admin/components/AdminFrame.tsx")

    assert 'title="总后台"' in page
    assert 'href: "/admin/conversations"' in frame
    assert 'href: "/admin/telegram-accounts"' in frame
    assert 'href: "/admin/data"' in frame
    assert 'href: "/admin/ai-ops"' in frame
    assert 'href: "/admin/approvals"' in frame
    assert 'href: "/admin/delivery"' in frame
    assert 'title: "会话流控"' in page
    assert 'title: "TG 真人账号"' in page
    assert 'title: "数据总览"' in page
    assert 'title: "AI 话术与人设"' in page
    assert 'title: "运营审批"' in page
    assert 'title: "推送监控与 H5"' in page


def test_admin_home_no_longer_links_legacy_pages() -> None:
    page = read("admin/app/page.tsx")
    frame = read("admin/components/AdminFrame.tsx")
    text = page + frame

    assert "/admin/operator-dashboard" not in text
    assert "/admin/scripts" not in text
    assert "/admin/memories" not in text
    assert "/admin/push" not in text
    assert "/admin/feedback" not in text
    assert "/admin/media" not in text
    assert "/admin/characters" in text


def test_conversation_overview_has_dedicated_route() -> None:
    page = read("admin/app/conversations/page.tsx")

    assert "会话总览" in page
    assert 'href="/admin"' in page
    assert 'href="/admin/telegram-accounts"' in page
    assert 'href="/admin/ai-ops"' in page
    assert 'href="/admin/approvals"' in page
    assert 'href="/admin/delivery"' in page
    assert "/admin/conversations?" in page


def test_business_flow_admin_pages_exist() -> None:
    pages = {
        "admin/app/ai-ops/page.tsx": ["话术库管理", "下载引导话术", "/ai-ops/admin/script-templates"],
        "admin/app/approvals/page.tsx": ["H-01", "H-07", "H-10", "H-11"],
        "admin/app/delivery/page.tsx": ["P4-09", "P4-10", "P5-08"],
        "admin/app/data/page.tsx": ["下载转化总览", "/admin/attribution/summary", "核心下载漏斗"],
    }

    for path, needles in pages.items():
        text = read(path)
        for needle in needles:
            assert needle in text


def test_approvals_page_shows_confirmed_statuses() -> None:
    page = read("admin/app/approvals/page.tsx")

    assert "待人工确认" not in page
    assert "2026-05-22 最终确认" in page
    assert "已批准" in page
    assert "已签字" in page
    assert "GO" in page


def test_data_page_covers_full_attribution_dashboard() -> None:
    page = read("admin/app/data/page.tsx")

    for needle in [
        "下载转化总览",
        "按日期",
        'type="date"',
        "TG 新用户数",
        "TG 接待用户数",
        "发送链接用户",
        "点击链接用户",
        "访问下载页",
        "完成下载",
        "链接点击率",
        "点击到下载页",
        "点击到下载",
        "平均点击耗时",
        "核心下载漏斗",
        "下载话术效果",
        "接待用户",
    ]:
        assert needle in page

    for needle in [
        "点击链接用户明细",
        "clicked_users",
        "排名规则：最近点击时间越近，越排在最上面。",
        "最多显示 500 个",
        "onDelete(row)",
        "/admin/attribution/clicked-users/",
        "最近链接",
    ]:
        assert needle in page


def test_unused_legacy_admin_pages_are_removed_but_character_page_stays() -> None:
    removed_pages = [
        "admin/app/operator-dashboard/page.tsx",
        "admin/app/scripts/page.tsx",
        "admin/app/memories/page.tsx",
        "admin/app/push/page.tsx",
        "admin/app/feedback/page.tsx",
        "admin/app/media/page.tsx",
    ]

    for path in removed_pages:
        assert not (ROOT / path).exists()
    assert (ROOT / "admin/app/characters/page.tsx").exists()


def test_login_entry_returns_to_admin_home() -> None:
    auth = read("admin/lib/auth.ts")

    assert "export const DEFAULT_ADMIN_ENTRY_PATH = ADMIN_BASE_PATH;" in auth
    assert "function getBrowserStorage(): Storage | null" in auth
    assert "return getBrowserStorage()?.getItem(TOKEN_KEY) ?? null;" in auth
