"""Insert only the api-green profile into an existing compose file."""

from __future__ import annotations

from pathlib import Path

COMPOSE = Path("/opt/eris/docker-compose.yml")
FRAGMENT = Path("/opt/eris/ops/compose/api-green-stage10.fragment.yml")
MARKER = "  prometheus:\n"


def main() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    if "\n  api-green:" in text or text.startswith("  api-green:"):
        raise SystemExit("api-green already present; refuse to insert twice")
    fragment = FRAGMENT.read_text(encoding="utf-8")
    if "8002:8000" in fragment:
        raise SystemExit("refuse: green fragment must not bind 8002")
    if "127.0.0.1:8003:8000" not in fragment:
        raise SystemExit("refuse: green fragment must bind 8003")
    if 'profiles: ["bluegreen"]' not in fragment:
        raise SystemExit("refuse: green fragment must stay behind bluegreen profile")
    if "PROCESS_ROLE: api" not in fragment:
        raise SystemExit("refuse: green fragment must use PROCESS_ROLE=api")
    index = text.find(MARKER)
    if index < 0:
        raise SystemExit("prometheus service marker not found")
    COMPOSE.write_text(text[:index] + fragment.rstrip() + "\n\n" + text[index:], encoding="utf-8")
    print("inserted api-green before prometheus")


if __name__ == "__main__":
    main()
