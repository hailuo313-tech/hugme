"""Accept Step B without touching the main API container."""

from __future__ import annotations

from pathlib import Path
import json
import subprocess

ROOT = Path("/opt/eris")


def run(args: list[str]) -> str:
    print("+", " ".join(args))
    return subprocess.check_output(args, text=True).strip()


def sql() -> dict:
    raw = run(
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
            "SELECT json_build_object('connected', (SELECT count(*)::int FROM telegram_accounts WHERE status='connected'), 'banned', (SELECT count(*)::int FROM telegram_accounts WHERE status='banned'), 'ownership', (SELECT count(*)::int FROM telegram_account_ownership), 'commands', (SELECT count(*)::int FROM runtime_commands));",
        ]
    )
    return json.loads(raw)


def main() -> None:
    before = Path("/tmp/step-b-api-before.txt").read_text(encoding="utf-8").strip()
    api = run(["docker", "inspect", "-f", "{{.Id}} {{.State.StartedAt}} {{.State.Health.Status}}", "eris-api"])
    print("api", api)
    if not api.startswith(before.split()[0]):
        raise SystemExit(f"main API container changed: before={before} after={api}")
    accounts = sql()
    print("accounts", accounts)
    if accounts.get("connected") != 360 or accounts.get("banned") != 152:
        raise SystemExit(f"telegram counts changed: {accounts}")
    if accounts.get("ownership") != 0:
        raise SystemExit(f"ownership must stay 0 before probe: {accounts}")

    health8000 = run(["curl", "-sS", "--max-time", "8", "http://127.0.0.1:8000/health"])
    print("health8000", health8000)
    compact = health8000.replace(" ", "")
    if '"process_role":"all"' not in compact or '"runtime_ready":true' not in compact:
        raise SystemExit("main API health drifted")

    health8004 = run(["curl", "-sS", "--max-time", "8", "http://127.0.0.1:8004/health"])
    print("health8004", health8004)
    compact4 = health8004.replace(" ", "")
    if '"process_role":"telegram_runtime"' not in compact4 or '"runtime_ready":true' not in compact4:
        raise SystemExit("runtime health failed")
    detail = subprocess.run(
        ["curl", "-sS", "--max-time", "8", "http://127.0.0.1:8004/health/detail"],
        capture_output=True,
        text=True,
    )
    print("detail8004", (detail.stdout or "").strip())
    if "owns_telegram_runtime" in (detail.stdout or "") and '"owns_telegram_runtime":false' in (detail.stdout or "").replace(" ", ""):
        raise SystemExit("runtime must own telegram runtime")

    names = run(["docker", "ps", "--format", "{{.Names}}"])
    if "eris-telegram-runtime-shadow" in names.splitlines() and "Up" in run(["docker", "ps", "--filter", "name=eris-telegram-runtime-shadow", "--format", "{{.Status}}"]):
        raise SystemExit("shadow container is still running")
    if "eris-telegram-runtime" not in names.splitlines():
        raise SystemExit("telegram-runtime is not running")

    logs = subprocess.run(
        ["docker", "logs", "--since", "10m", "eris-telegram-runtime"],
        capture_output=True,
        text=True,
    )
    combined = (logs.stdout or "") + (logs.stderr or "")
    if "Successfully restored session" in combined:
        raise SystemExit("runtime must not restore sessions in step B")
    if "runtime_consumer.started" not in combined:
        raise SystemExit("runtime consumer did not start")
    if "runtime_shadow.consumer.started" in combined:
        raise SystemExit("real runtime started the shadow consumer")

    run(["docker", "cp", str(ROOT / "ops/compose/probe_step_b.py"), "eris-telegram-runtime:/tmp/probe_step_b.py"])
    print(
        run(
            [
                "docker",
                "compose",
                "-f",
                str(ROOT / "docker-compose.yml"),
                "--profile",
                "telegram-runtime",
                "exec",
                "-T",
                "-e",
                "PYTHONPATH=/app",
                "-w",
                "/app",
                "telegram-runtime",
                "python",
                "/tmp/probe_step_b.py",
            ]
        )
    )
    after_probe = sql()
    print("after_probe", after_probe)
    if after_probe.get("connected") != 360 or after_probe.get("ownership") != 0:
        raise SystemExit(f"probe leaked state: {after_probe}")

    api_logs = subprocess.run(
        ["docker", "logs", "--since", "20m", "eris-api"],
        capture_output=True,
        text=True,
    )
    dup = ((api_logs.stdout or "") + (api_logs.stderr or "")).count("AuthKeyDuplicated")
    print("AuthKeyDuplicated", dup)
    if dup:
        raise SystemExit("AuthKeyDuplicated appeared after Step B")
    print("stepB accepted")


if __name__ == "__main__":
    main()
