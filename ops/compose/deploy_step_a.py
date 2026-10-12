"""Apply Step A patches and rebuild only the main API."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path("/opt/eris")
SRC = Path("/tmp/step-a-upload")


def run(args: list[str]) -> str:
    print("+", " ".join(args))
    return subprocess.check_output(args, text=True).strip()


def main() -> None:
    ops = ROOT / "ops/compose"
    ops.mkdir(parents=True, exist_ok=True)
    for name in (
        "backup_step_a.py",
        "patch_runtime_split_step_a.py",
        "verify_step_a_hold.py",
        "deploy_step_a.py",
        "wait_step_a_sessions.py",
        "probe_step_a.py",
        "accept_step_a.py",
        "stage_a_prod_snip.py",
    ):
        src = SRC / name
        if src.exists():
            shutil.copy2(src, ops / name)
    print(run(["python3", str(ops / "backup_step_a.py")]))
    print(run(["python3", str(ops / "patch_runtime_split_step_a.py")]))
    before = run(
        ["docker", "inspect", "-f", "{{.Id}} {{.State.StartedAt}}", "eris-api"]
    )
    print("api_before", before)
    run(
        [
            "docker",
            "compose",
            "-f",
            str(ROOT / "docker-compose.yml"),
            "up",
            "-d",
            "--build",
            "api",
        ]
    )
    deadline = time.time() + 420
    last = ""
    while time.time() < deadline:
        proc = subprocess.run(
            ["curl", "-sS", "--max-time", "8", "http://127.0.0.1:8000/health"],
            capture_output=True,
            text=True,
        )
        last = (proc.stdout or "").strip()
        compact = last.replace(" ", "")
        if '"process_role":"all"' in compact and '"runtime_ready":true' in compact:
            print("health", last)
            break
        time.sleep(5)
    else:
        raise SystemExit(f"api did not become ready: {last}")
    after = run(
        ["docker", "inspect", "-f", "{{.Id}} {{.State.StartedAt}} {{.State.Health.Status}}", "eris-api"]
    )
    print("api_after", after)
    print("stepA deploy finished; wait for 360 session restore before probe")


if __name__ == "__main__":
    main()
