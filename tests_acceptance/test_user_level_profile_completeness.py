from __future__ import annotations

from services.user_level_service import UserLevelService


class _Row(dict):
    @property
    def _mapping(self):
        return self


def test_profile_signals_read_country_column_and_age_preference() -> None:
    signals = UserLevelService()._profile_signals_from_row(
        _Row(
            country_code="us",
            preferences={"age": 29},
            lifetime_spend_cents=0,
            vip_level=0,
            user_level="C",
        )
    )

    assert signals.country_code == "US"
    assert signals.age == 29


def test_profile_signals_accept_ai_extracted_age() -> None:
    signals = UserLevelService()._profile_signals_from_row(
        _Row(
            country_code="JP",
            preferences={"ai_extracted_age": {"age": 34}},
            lifetime_spend_cents=9900,
            vip_level=0,
            user_level="C",
        )
    )

    assert signals.country_code == "JP"
    assert signals.age == 34
    assert signals.lifetime_spend_usd == 99.0
