#!/usr/bin/env python3
"""C-09: WebSocket protocol conformance audit."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from services.ws_protocol_conformance import (  # noqa: E402
    implementation_contract,
    validate_client_event,
    validate_server_event,
)

FIXTURES = ROOT / "fixtures" / "c09_ws_protocol.json"
DOC = ROOT / "docs" / "ws_protocol.md"


def main() -> int:
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    failed = 0
    if not DOC.is_file():
        print(f"FAIL: missing {DOC}")
        failed += 1

    for case in data["valid_server_events"]:
        errs = validate_server_event(case["payload"])
        if errs:
            print(f"FAIL {case['id']}: {errs}")
            failed += 1
        else:
            print(f"PASS {case['id']} server/{case['type']}")

    for case in data["valid_client_events"]:
        errs = validate_client_event(case["payload"])
        if errs:
            print(f"FAIL {case['id']}: {errs}")
            failed += 1
        else:
            print(f"PASS {case['id']} client")

    for case in data["invalid_server_events"]:
        if not validate_server_event(case["payload"]):
            print(f"FAIL {case['id']}: expected validation errors")
            failed += 1
        else:
            print(f"PASS {case['id']} rejected ({case.get('reason', '')})")

    contract = implementation_contract()
    print(f"Contract: path={contract['ws_path']} poll_ms={contract['poll_interval_ms']}")
    print(f"  server_events={len(contract['server_event_types'])} tracked={contract['tracked_delta_fields']}")

    if failed:
        print(f"\nC-09 audit: {failed} failure(s)")
        return 1
    print("\nC-09 audit: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
