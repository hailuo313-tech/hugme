"""Insert Stage 8 canary flag. Does not start a switcher and does not rebuild API."""

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
        "config canary validator": "def _empty_canary_to_false",
        "config canary default": "RUNTIME_CANARY_ENABLED: bool = False",
        "compose api canary flag": "RUNTIME_CANARY_ENABLED:",
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
    if (ROOT / "app/services/runtime_legacy_shutdown.py").exists():
        raise SystemExit("refuse: stage 9 shutdown module is present")
    must_replace(
        "app/core/config.py",
        """    def _empty_shadow_mode_to_false(cls, v: object) -> object:
        if v is None or v == "":
            return False
        return v
    # D2-2: 上游 LLM 失败时是否回退为 "echo: <user_text>"。
""",
        """    def _empty_shadow_mode_to_false(cls, v: object) -> object:
        if v is None or v == "":
            return False
        return v

    @field_validator("RUNTIME_CANARY_ENABLED", mode="before")
    @classmethod
    def _empty_canary_to_false(cls, v: object) -> object:
        if v is None or v == "":
            return False
        return v
    # D2-2: 上游 LLM 失败时是否回退为 "echo: <user_text>"。
""",
        "config canary validator",
    )
    must_replace(
        "app/core/config.py",
        """    RUNTIME_SHADOW_MODE: bool = False
    # P1-18：Session 管理器配置（自动重连 + 健康检查）
""",
        """    RUNTIME_SHADOW_MODE: bool = False
    # 阶段 8：Canary 逐账号迁移。生产默认关，没有人工打开时不会切换任何账号。
    RUNTIME_CANARY_ENABLED: bool = False
    # P1-18：Session 管理器配置（自动重连 + 健康检查）
""",
        "config canary default",
    )
    example = ROOT / ".env.example"
    if example.exists():
        text = example.read_text(encoding="utf-8")
        if "RUNTIME_CANARY_ENABLED" not in text:
            if "RUNTIME_SHADOW_MODE=0\n" in text:
                example.write_text(
                    text.replace(
                        "RUNTIME_SHADOW_MODE=0\n",
                        "RUNTIME_SHADOW_MODE=0\nRUNTIME_CANARY_ENABLED=0\n",
                        1,
                    ),
                    encoding="utf-8",
                )
                print("patched .env.example")
            else:
                example.write_text(text.rstrip() + "\nRUNTIME_CANARY_ENABLED=0\n", encoding="utf-8")
                print("appended .env.example")
    template = ROOT / ".env.template"
    if template.exists():
        text = template.read_text(encoding="utf-8")
        if "RUNTIME_CANARY_ENABLED" not in text:
            if "RUNTIME_SHADOW_MODE=0\n" in text:
                template.write_text(
                    text.replace(
                        "RUNTIME_SHADOW_MODE=0\n",
                        "RUNTIME_SHADOW_MODE=0\nRUNTIME_CANARY_ENABLED=0\n",
                        1,
                    ),
                    encoding="utf-8",
                )
                print("patched .env.template")
            else:
                template.write_text(text.rstrip() + "\nRUNTIME_CANARY_ENABLED=0\n", encoding="utf-8")
                print("appended .env.template")
    must_replace(
        "docker-compose.yml",
        """      PROCESS_ROLE: ${PROCESS_ROLE:-all}
      RUNTIME_SHADOW_MODE: ${RUNTIME_SHADOW_MODE:-false}
      OPS_DOCS_DIR: /srv/ops-docs
""",
        """      PROCESS_ROLE: ${PROCESS_ROLE:-all}
      RUNTIME_SHADOW_MODE: ${RUNTIME_SHADOW_MODE:-false}
      RUNTIME_CANARY_ENABLED: ${RUNTIME_CANARY_ENABLED:-false}
      OPS_DOCS_DIR: /srv/ops-docs
""",
        "compose api canary flag",
    )
    print("stage8 patches applied")


if __name__ == "__main__":
    main()
