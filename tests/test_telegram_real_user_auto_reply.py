from types import SimpleNamespace

import pytest

from services.telegram_real_user_auto_reply import _is_managed_telegram_account


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Db:
    def __init__(self, row):
        self.row = row
        self.params = None

    async def execute(self, _statement, params=None):
        self.params = params or {}
        return _Result(self.row)


@pytest.mark.asyncio
async def test_managed_telegram_account_sender_is_skipped():
    db = _Db(SimpleNamespace(found=True))

    assert await _is_managed_telegram_account(db, "tg_7518020047") is True
    assert db.params["telegram_user_id"] == 7518020047


@pytest.mark.asyncio
async def test_unmanaged_telegram_sender_is_not_skipped():
    assert await _is_managed_telegram_account(_Db(None), "tg_7058432267") is False
    assert await _is_managed_telegram_account(_Db(SimpleNamespace()), "web_7058432267") is False
    assert await _is_managed_telegram_account(_Db(SimpleNamespace()), "tg_not_numeric") is False
