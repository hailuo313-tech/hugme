from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from services.regression_gate import run_regression_gate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run P5-03 level/intent regression gate.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON summary.",
    )
    args = parser.parse_args()

    result = run_regression_gate()
    payload = result.model_dump()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            f"P5-03 regression: status={payload['status']} "
            f"passed={payload['passed']} failed={payload['failed']} total={payload['total']}"
        )
        for suite in payload["suites"]:
            print(
                f"- {suite['suite']}: passed={suite['passed']} "
                f"failed={suite['failed']} total={suite['total']} accuracy={suite['accuracy']:.2%}"
            )
            for failure in suite["failures"]:
                print(
                    f"  - {failure['case_id']}: expected={failure['expected']} "
                    f"actual={failure['actual']}"
                )

    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
