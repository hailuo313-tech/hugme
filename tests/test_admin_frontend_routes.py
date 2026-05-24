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
    assert "/admin/characters" not in text
    assert "/admin/memories" not in text
    assert "/admin/push" not in text
    assert "/admin/feedback" not in text
    assert "/admin/media" not in text


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
        "admin/app/data/page.tsx": ["链接与 App 转化", "/admin/attribution/summary", "Top 点击话术"],
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
        "今日链接点击人数",
        "按天查询",
        'type="date"',
        "点击率",
        "下载转化率",
        "注册转化率",
        "付费转化率",
        "点击到注册平均耗时",
        "点击到首付平均耗时",
        "TG 新用户数",
        "TG 接待用户数",
        "TG 账号接待",
        "接待用户",
        "Top 下载话术",
        "Top 注册话术",
        "Top 付费话术",
        "年龄段点击排行",
        "各等级点击与付费",
        "国家 / T1",
        "TG 账号转化",
        "单条链接明细",
    ]:
        assert needle in page


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
