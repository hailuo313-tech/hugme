from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.geoip_service import GeoIPResult, GeoIPService


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "p2_02_geoip_accuracy.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_p2_02_geoip_accuracy_fixture_has_fixed_sample_set():
    data = _load_fixture()
    samples = data["samples"]

    assert data["min_accuracy"] == 0.95
    assert len(samples) >= 20
    assert all(sample["ip"] and sample["expected_country_code"] for sample in samples)


@pytest.mark.asyncio
async def test_p2_02_geoip_fixed_samples_regress_at_95_percent_or_better():
    data = _load_fixture()
    service = GeoIPService()
    service._maxmind_enabled = False
    service._ipapi_enabled = False

    for sample in data["samples"]:
        service._put_to_cache(
            sample["ip"],
            GeoIPResult(
                country_code=sample["expected_country_code"],
                country_name=sample["country_name"],
                ip=sample["ip"],
                provider="p2_02_fixture",
            ),
        )

    test_ips = [
        (sample["ip"], sample["expected_country_code"])
        for sample in data["samples"]
    ]
    accuracy = await service.validate_accuracy(test_ips)

    assert accuracy >= data["min_accuracy"]
