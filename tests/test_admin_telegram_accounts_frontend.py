from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_telegram_accounts_admin_uses_api_fetch_relative_paths() -> None:
    page = (ROOT / "admin" / "app" / "telegram-accounts" / "page.tsx").read_text(
        encoding="utf-8"
    )

    assert 'href="/admin/telegram-accounts"' in (
        ROOT / "admin" / "app" / "page.tsx"
    ).read_text(encoding="utf-8")
    assert 'apiFetch<TelegramAccountsResponse>("/telegram/accounts")' in page
    assert 'apiFetch("/telegram/accounts"' in page
    assert 'apiFetch("/api/v1/telegram/accounts' not in page
    assert 'apiFetch(`/api/v1/telegram/accounts' not in page
