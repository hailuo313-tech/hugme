"""Insert only the telegram-runtime profile into an existing compose file."""

from __future__ import annotations

from pathlib import Path

COMPOSE = Path("/opt/eris/docker-compose.yml")
FRAGMENT = Path("/opt/eris/ops/compose/telegram-runtime-stepb.fragment.yml")
MARKER = "  prometheus:\n"


def main() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    if "\n  telegram-runtime:" in text or text.startswith("  telegram-runtime:"):
        raise SystemExit("telegram-runtime already present; refuse to insert twice")
    if (Path("/tmp/step-b-upload") / "docker-compose.yml").exists():
        raise SystemExit("refuse: do not upload a whole compose file")
    fragment = FRAGMENT.read_text(encoding="utf-8")
    if "127.0.0.1:8004:8000" not in fragment:
        raise SystemExit("refuse: runtime fragment must bind 8004")
    if "8000:8000" in fragment or "8001:8000" in fragment:
        raise SystemExit("refuse: runtime must not bind 8000/8001")
    if 'profiles: ["telegram-runtime"]' not in fragment:
        raise SystemExit("refuse: runtime fragment must stay behind telegram-runtime profile")
    if "PROCESS_ROLE: telegram_runtime" not in fragment:
        raise SystemExit("refuse: runtime must use PROCESS_ROLE=telegram_runtime")
    if 'RUNTIME_SHADOW_MODE: "false"' not in fragment:
        raise SystemExit("refuse: real runtime must not be shadow")
    if "depends_on:\n      api:" in fragment:
        raise SystemExit("refuse: runtime must not depend on api")
    index = text.find(MARKER)
    if index < 0:
        raise SystemExit("prometheus service marker not found")
    COMPOSE.write_text(text[:index] + fragment.rstrip() + "\n\n" + text[index:], encoding="utf-8")
    print("inserted telegram-runtime before prometheus")


if __name__ == "__main__":
    main()
