"""Apply Step B files, stop shadow, start only telegram-runtime. Never rebuild api."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path("/opt/eris")
SRC = Path("/tmp/step-b-upload")


def run(args: list[str]) -> str:
    print("+", " ".join(args))
    return subprocess.check_output(args, text=True).strip()


def main() -> None:
    if (SRC / "docker-compose.yml").exists():
        raise SystemExit("refuse: do not upload a whole compose file")
    ops = ROOT / "ops/compose"
    ops.mkdir(parents=True, exist_ok=True)
    for name in (
        "backup_step_b.py",
        "patch_runtime_split_step_b.py",
        "insert_telegram_runtime_step_b.py",
        "telegram-runtime-stepb.fragment.yml",
        "deploy_step_b.py",
        "wait_step_a_sessions.py",
        "verify_step_b.py",
        "probe_step_b.py",
        "accept_step_b.py",
    ):
        src = SRC / name
        if src.exists():
            shutil.copy2(src, ops / name)
            print("installed", ops / name)

    consumer = SRC / "runtime_command_consumer.py"
    if not consumer.exists():
        raise SystemExit("missing runtime_command_consumer.py")
    shutil.copy2(consumer, ROOT / "app/services/runtime_command_consumer.py")
    print("installed", ROOT / "app/services/runtime_command_consumer.py")

    before = run(["docker", "inspect", "-f", "{{.Id}} {{.State.StartedAt}}", "eris-api"])
    print("api_before", before)
    (Path("/tmp/step-b-api-before.txt")).write_text(before + "\n", encoding="utf-8")

    print(run(["python3", str(ops / "backup_step_b.py")]))
    print(run(["python3", str(ops / "patch_runtime_split_step_b.py")]))
    print(run(["python3", str(ops / "insert_telegram_runtime_step_b.py")]))

    run(
        [
            "docker",
            "compose",
            "-f",
            str(ROOT / "docker-compose.yml"),
            "--profile",
            "runtime-shadow",
            "stop",
            "telegram-runtime-shadow",
        ]
    )
    print("stopped shadow")
    run(
        [
            "docker",
            "compose",
            "-f",
            str(ROOT / "docker-compose.yml"),
            "--profile",
            "telegram-runtime",
            "up",
            "-d",
            "--build",
            "telegram-runtime",
        ]
    )
    deadline = time.time() + 180
    last = ""
    while time.time() < deadline:
        proc = subprocess.run(
            ["curl", "-sS", "--max-time", "8", "http://127.0.0.1:8004/health"],
            capture_output=True,
            text=True,
        )
        last = (proc.stdout or "").strip()
        compact = last.replace(" ", "")
        if '"process_role":"telegram_runtime"' in compact and '"runtime_ready":true' in compact:
            print("runtime_health", last)
            break
        time.sleep(3)
    else:
        raise SystemExit(f"telegram-runtime did not become ready: {last}")

    after = run(["docker", "inspect", "-f", "{{.Id}} {{.State.StartedAt}}", "eris-api"])
    print("api_after", after)
    if after != before:
        raise SystemExit("refuse: main API container changed; step B must not rebuild api")
    print("stepB deploy finished; run accept next")


if __name__ == "__main__":
    main()
