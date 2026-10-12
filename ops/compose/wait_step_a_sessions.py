from pathlib import Path
import json
import subprocess
import time

ROOT = Path("/opt/eris")


def sql() -> dict:
    raw = subprocess.check_output(
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
            "SELECT json_build_object('connected', (SELECT count(*)::int FROM telegram_accounts WHERE status='connected'), 'banned', (SELECT count(*)::int FROM telegram_accounts WHERE status='banned'), 'ownership', (SELECT count(*)::int FROM telegram_account_ownership));",
        ],
        text=True,
    ).strip()
    return json.loads(raw)


def main() -> None:
    deadline = time.time() + 420
    last = {}
    while time.time() < deadline:
        last = sql()
        print("accounts", last)
        if last.get("connected") == 360 and last.get("banned") == 152 and last.get("ownership") == 0:
            print("session restore accepted")
            return
        time.sleep(10)
    raise SystemExit(f"session restore timeout: {last}")


if __name__ == "__main__":
    main()
