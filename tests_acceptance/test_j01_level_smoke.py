"""C-06: J-01 smoke fixtures must pass 10/10."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from services.level_engine import UserLevelInput, calc_user_level

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "j01_level_smoke.json"


def _fixtures() -> list[dict]:
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    return list(data["fixtures"])


@pytest.mark.parametrize("fix", _fixtures(), ids=[f["id"] for f in _fixtures()])
def test_j01_fixture(fix: dict):
    raw = fix["input"]
    inp = UserLevelInput(
        profile_complete=bool(raw["profile_complete"]),
        country_code=raw.get("country_code"),
        lifetime_spend_usd=float(raw.get("lifetime_spend_usd", 0)),
        vip_level=int(raw.get("vip_level", 0)),
        operator_assigned_s=bool(raw.get("operator_assigned_s", False)),
    )
    result = calc_user_level(inp)
    got = {
        "level": result.level,
        "chat_route": result.chat_route,
        "reason": result.reason,
        "country_tier": result.country_tier,
    }
    assert got == fix["expect"], f"{fix['id']}: got {got} expect {fix['expect']}"


def test_j01_fixture_count():
    assert len(_fixtures()) == 10


def test_j01_cli_runner_exit_zero():
    script = ROOT / "scripts" / "j01_level_smoke.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--no-report"],
        cwd=str(ROOT),
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "app")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
