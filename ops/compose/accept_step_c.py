"""Accept Step C: switcher installed, no live account moved, API not rebuilt."""

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
    before = Path("/tmp/step-c-api-before.txt").read_text(encoding="utf-8").strip()
    api = run(
        ["docker", "inspect", "-f", "{{.Id}} {{.State.StartedAt}} {{.State.Health.Status}}", "eris-api"]
    )
    print("api", api)
    if not api.startswith(before.split()[0]):
        raise SystemExit(f"main API container changed: before={before} after={api}")
    accounts = sql()
    print("accounts", accounts)
    if accounts.get("connected") != 360 or accounts.get("banned") != 152:
        raise SystemExit(f"telegram counts changed: {accounts}")
    if accounts.get("ownership") != 0:
        raise SystemExit(f"ownership must stay 0: {accounts}")

    health = run(["curl", "-sS", "--max-time", "8", "http://127.0.0.1:8000/health"]).replace(" ", "")
    if '"process_role":"all"' not in health or '"runtime_ready":true' not in health:
        raise SystemExit("main API health drifted")
    rt = run(["curl", "-sS", "--max-time", "8", "http://127.0.0.1:8004/health"]).replace(" ", "")
    if '"process_role":"telegram_runtime"' not in rt or '"runtime_ready":true' not in rt:
        raise SystemExit("runtime health drifted")

    run(["docker", "cp", str(ROOT / "ops/compose/probe_step_c.py"), "eris-telegram-runtime:/tmp/probe_step_c.py"])
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
                "/tmp/probe_step_c.py",
            ]
        )
    )
    after = sql()
    print("after_probe", after)
    if after.get("connected") != 360 or after.get("ownership") != 0:
        raise SystemExit(f"probe leaked state: {after}")
    api_logs = subprocess.run(
        ["docker", "logs", "--since", "20m", "eris-api"],
        capture_output=True,
        text=True,
    )
    dup = ((api_logs.stdout or "") + (api_logs.stderr or "")).count("AuthKeyDuplicated")
    print("AuthKeyDuplicated", dup)
    if dup:
        raise SystemExit("AuthKeyDuplicated appeared after Step C")
    print("stepC accepted")


if __name__ == "__main__":
    main()
