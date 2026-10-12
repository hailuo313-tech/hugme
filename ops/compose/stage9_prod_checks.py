"""Stage 9 host-side before/after checks. Read-only except printing facts."""

from __future__ import annotations

from pathlib import Path
import hashlib
import subprocess

ROOT = Path("/opt/eris")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(args: list[str]) -> str:
    return subprocess.check_output(args, text=True).strip()


def main() -> None:
    files = [
        "app/services/runtime_legacy_shutdown.py",
        "app/services/runtime_canary.py",
        "app/core/config.py",
        "docker-compose.yml",
        "app/main.py",
        ".env.example",
        ".env.template",
        ".env",
    ]
    print("=== FILES ===")
    for rel in files:
        path = ROOT / rel
        if path.exists():
            print(f"{rel}\texists=1\tsha={sha256(path)}")
        else:
            print(f"{rel}\texists=0")

    print("=== GREP ===")
    for rel in ["app/core/config.py", "docker-compose.yml", "app/main.py", ".env", ".env.example", ".env.template"]:
        path = ROOT / rel
        if not path.exists():
            print(rel, "MISSING")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        print(
            rel,
            "legacy_flag",
            int("LEGACY_TELEGRAM_RUNTIME_ENABLED" in text),
            "shutdown_import",
            int("runtime_legacy_shutdown" in text),
            "api_green",
            int("api-green" in text),
        )

    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    print("compose_api_green", int("\n  api-green:" in compose))
    print("compose_legacy_flag", int("LEGACY_TELEGRAM_RUNTIME_ENABLED" in compose))

    print("=== HEALTH ===")
    print(run(["curl", "-sS", "http://127.0.0.1:8000/health"]))

    print("=== DOCKER API ===")
    print(
        run(
            [
                "docker",
                "inspect",
                "-f",
                "{{.Id}} {{.State.StartedAt}} {{.State.Status}} {{.State.Health.Status}}",
                "eris-api",
            ]
        )
    )
    print(run(["docker", "compose", "-f", str(ROOT / "docker-compose.yml"), "ps", "--format", "{{.Name}} {{.Status}}"]))

    print("=== CONTAINER ===")
    print(
        run(
            [
                "docker",
                "exec",
                "eris-api",
                "python",
                "-c",
                (
                    "import os,pathlib;"
                    "p=pathlib.Path('/app/services/runtime_legacy_shutdown.py');"
                    "c=pathlib.Path('/app/core/config.py').read_text();"
                    "m=pathlib.Path('/app/main.py').read_text();"
                    "print('container_shutdown', int(p.exists()));"
                    "print('container_config_flag', int('LEGACY_TELEGRAM_RUNTIME_ENABLED' in c));"
                    "print('container_main_shutdown', int('runtime_legacy_shutdown' in m));"
                    "print('container_env_legacy', os.environ.get('LEGACY_TELEGRAM_RUNTIME_ENABLED','UNSET'))"
                ),
            ]
        )
    )

    sql = (
        "SELECT json_build_object("
        "'accounts', (SELECT json_object_agg(status, cnt) FROM ("
        "SELECT status, count(*)::int AS cnt FROM telegram_accounts GROUP BY status) s),"
        "'ownership', (SELECT count(*)::int FROM telegram_account_ownership),"
        "'commands', (SELECT count(*)::int FROM runtime_commands)"
        ");"
    )
    print("=== SQL ===")
    print(
        run(
            [
                "docker",
                "compose",
                "-f",
                str(ROOT / "docker-compose.yml"),
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "eris",
                "-d",
                "eris",
                "-tA",
                "-c",
                sql,
            ]
        )
    )

    print("=== AUTHKEY ===")
    proc = subprocess.run(
        ["docker", "logs", "--since", "1h", "eris-api"],
        capture_output=True,
        text=True,
    )
    logs = (proc.stdout or "") + (proc.stderr or "")
    print("AuthKeyDuplicated", logs.count("AuthKeyDuplicated"))


if __name__ == "__main__":
    main()
