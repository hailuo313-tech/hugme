"""Insert only the api-next profile into an existing compose file."""

from __future__ import annotations

from pathlib import Path

COMPOSE = Path("/opt/eris/docker-compose.yml")
FRAGMENT = Path("/opt/eris/ops/compose/api-next-stage5.fragment.yml")
MARKER = "  prometheus:\n"


def main() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    if "\n  api-next:" in text or text.startswith("  api-next:"):
        raise SystemExit("api-next already present; refuse to insert twice")
    if "\n  api-green:" in text:
        raise SystemExit("api-green present; stage 5 must not add bluegreen")
    fragment = FRAGMENT.read_text(encoding="utf-8").rstrip() + "\n\n"
    index = text.find(MARKER)
    if index < 0:
        raise SystemExit("prometheus service marker not found")
    COMPOSE.write_text(text[:index] + fragment + text[index:], encoding="utf-8")
    print("inserted api-next before prometheus")


if __name__ == "__main__":
    main()
