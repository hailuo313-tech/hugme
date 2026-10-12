from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_admin_characters_page_exists_and_exposes_tone_controls() -> None:
    page = (ROOT / "admin" / "app" / "characters" / "page.tsx").read_text(
        encoding="utf-8"
    )

    assert "角色管理" in page
    assert "+ 新建角色" in page
    assert 'Input label="语气"' in page
    for label in ("温柔度", "主动度", "调情度", "幽默度", "情感深度", "边界感"):
        assert label in page
    assert "回复长度" in page
    assert "Emoji 频率" in page


def test_admin_navigation_links_to_characters_page() -> None:
    frame = (ROOT / "admin" / "components" / "AdminFrame.tsx").read_text(
        encoding="utf-8"
    )
    home = (ROOT / "admin" / "app" / "page.tsx").read_text(encoding="utf-8")

    assert 'href: "/admin/characters"' in frame
    assert 'label: "角色"' in frame
    assert "角色与语气" in home
    assert 'href: "/admin/characters"' in home
