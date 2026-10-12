"""Insert Stage 9 legacy-shutdown flag. Does not stop Legacy and does not rebuild API."""

from __future__ import annotations

from pathlib import Path

ROOT = Path("/opt/eris")


def _load(rel: str) -> tuple[Path, str, str]:
    path = ROOT / rel
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8").replace("\r\n", "\n")
    return path, text, newline


def must_replace(rel: str, old: str, new: str, label: str) -> None:
    path, text, newline = _load(rel)
    old = old.replace("\r\n", "\n")
    new = new.replace("\r\n", "\n")
    marker = {
        "config legacy validator": "def _empty_legacy_runtime_to_true",
        "config legacy default": "LEGACY_TELEGRAM_RUNTIME_ENABLED: bool = True",
        "compose api legacy flag": "LEGACY_TELEGRAM_RUNTIME_ENABLED:",
    }.get(label)
    if marker and marker in text:
        print("skip", label, "(already present)")
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match in {rel}, found {count}")
    path.write_text(text.replace(old, new, 1).replace("\n", newline), encoding="utf-8")
    print("patched", label)


def main() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    if "\n  api-green:" in compose:
        raise SystemExit("refuse: production compose has api-green; stage 9 must not add bluegreen")
    if "runtime_legacy_shutdown" in (ROOT / "app/main.py").read_text(encoding="utf-8"):
        raise SystemExit("refuse: main.py already imports shutdown")

    must_replace(
        "app/core/config.py",
        """    def _empty_canary_to_false(cls, v: object) -> object:
        if v is None or v == "":
            return False
        return v
    # D2-2: 上游 LLM 失败时是否回退为 "echo: <user_text>"。
""",
        """    def _empty_canary_to_false(cls, v: object) -> object:
        if v is None or v == "":
            return False
        return v

    @field_validator("LEGACY_TELEGRAM_RUNTIME_ENABLED", mode="before")
    @classmethod
    def _empty_legacy_runtime_to_true(cls, v: object) -> object:
        if v is None or v == "":
            return True
        return v
    # D2-2: 上游 LLM 失败时是否回退为 "echo: <user_text>"。
""",
        "config legacy validator",
    )
    must_replace(
        "app/core/config.py",
        """    RUNTIME_CANARY_ENABLED: bool = False
    # P1-18：Session 管理器配置（自动重连 + 健康检查）
""",
        """    RUNTIME_CANARY_ENABLED: bool = False
    # 阶段 9：关闭 Legacy Telegram Runtime。生产默认 true，没有人工关闭时 Legacy 继续跑。
    LEGACY_TELEGRAM_RUNTIME_ENABLED: bool = True
    # P1-18：Session 管理器配置（自动重连 + 健康检查）
""",
        "config legacy default",
    )
    example = ROOT / ".env.example"
    if example.exists():
        text = example.read_text(encoding="utf-8")
        if "LEGACY_TELEGRAM_RUNTIME_ENABLED" not in text:
            if "RUNTIME_CANARY_ENABLED=0\n" in text:
                example.write_text(
                    text.replace(
                        "RUNTIME_CANARY_ENABLED=0\n",
                        "RUNTIME_CANARY_ENABLED=0\nLEGACY_TELEGRAM_RUNTIME_ENABLED=1\n",
                        1,
                    ),
                    encoding="utf-8",
                )
                print("patched .env.example")
            else:
                example.write_text(text.rstrip() + "\nLEGACY_TELEGRAM_RUNTIME_ENABLED=1\n", encoding="utf-8")
                print("appended .env.example")
    template = ROOT / ".env.template"
    if template.exists():
        text = template.read_text(encoding="utf-8")
        if "LEGACY_TELEGRAM_RUNTIME_ENABLED" not in text:
            if "RUNTIME_CANARY_ENABLED=0\n" in text:
                template.write_text(
                    text.replace(
                        "RUNTIME_CANARY_ENABLED=0\n",
                        "RUNTIME_CANARY_ENABLED=0\nLEGACY_TELEGRAM_RUNTIME_ENABLED=1\n",
                        1,
                    ),
                    encoding="utf-8",
                )
                print("patched .env.template")
            else:
                template.write_text(text.rstrip() + "\nLEGACY_TELEGRAM_RUNTIME_ENABLED=1\n", encoding="utf-8")
                print("appended .env.template")
    must_replace(
        "docker-compose.yml",
        """      RUNTIME_CANARY_ENABLED: ${RUNTIME_CANARY_ENABLED:-false}
      OPS_DOCS_DIR: /srv/ops-docs
""",
        """      RUNTIME_CANARY_ENABLED: ${RUNTIME_CANARY_ENABLED:-false}
      LEGACY_TELEGRAM_RUNTIME_ENABLED: ${LEGACY_TELEGRAM_RUNTIME_ENABLED:-true}
      OPS_DOCS_DIR: /srv/ops-docs
""",
        "compose api legacy flag",
    )
    print("stage9 patches applied")


if __name__ == "__main__":
    main()
