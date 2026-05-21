from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECONNECT_LIB = ROOT / "admin" / "lib" / "wsReconnect.ts"
WS_HOOK = ROOT / "admin" / "hooks" / "useOperatorTaskWs.ts"
WS_STATUS = ROOT / "admin" / "components" / "OperatorWsStatus.tsx"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_p4_07_reconnect_policy_recovers_within_10s() -> None:
    text = _read(RECONNECT_LIB)

    assert "WS_RECONNECT_RECOVERY_SLA_MS = 10000" in text
    assert "WS_RECONNECT_INITIAL_DELAY_MS = 1000" in text
    assert "WS_RECONNECT_MAX_DELAY_MS = 8000" in text
    assert "Math.min" in text


def test_p4_07_hook_reconnects_after_close_and_resets_on_open() -> None:
    text = _read(WS_HOOK)

    assert 'setConnState("reconnecting")' in text
    assert "nextReconnectDelayMs(reconnectAttemptRef.current)" in text
    assert "setTimeout(() => connect(), delayMs)" in text
    assert re.search(r"ws\.onopen = \(\) => \{[^}]*reconnectAttemptRef\.current = 0;", text, re.S)


def test_p4_07_hook_refreshes_snapshot_after_reconnect() -> None:
    text = _read(WS_HOOK)

    assert 'msg.type === "task.snapshot"' in text
    assert "onTaskSnapshot" in text
    assert 'msg.type === "task.removed"' in text
    assert "onTaskRemoved" in text


def test_p4_07_status_allows_manual_reconnect_while_reconnecting() -> None:
    text = _read(WS_STATUS)

    assert 'connState === "reconnecting"' in text
    assert 'connState === "disconnected" || connState === "reconnecting"' in text
