from __future__ import annotations

import pytest

from services.call_broadcast.incoming_review import inbound_call_requires_operator_review
from services.call_broadcast.jobs import resolve_inbound_call_context


class _RowsResult:
    def __init__(self, value):
        self.value = value

    def first(self):
        return self.value


class _MappingRow:
    def __init__(self, data):
        self._mapping = data


@pytest.mark.asyncio
async def test_resolve_inbound_call_context_from_completed_count():
    class _Db:
        async def execute(self, statement, params=None):
            return _RowsResult(_MappingRow({"cnt": 2}))

    ctx = await resolve_inbound_call_context(_Db(), 12345)
    assert ctx == {"completed_inbound_calls": 2, "inbound_call_number": 3}


def test_first_inbound_call_auto_answered():
    assert inbound_call_requires_operator_review(0) is False


def test_second_inbound_call_auto_answered():
    assert inbound_call_requires_operator_review(1) is False


def test_third_inbound_call_requires_operator_review():
    assert inbound_call_requires_operator_review(2) is True
