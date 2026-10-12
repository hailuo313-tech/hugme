"""Install api-green profile and start only that sidecar. Never recreate the main API."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path("/opt/eris")
SRC = Path("/tmp/stage10-upload")


def run(args: list[str]) -> str:
    print("+", " ".join(args))
    return subprocess.check_output(args, text=True).strip()


def main() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    if "\n  api-green:" in compose:
        raise SystemExit("refuse: api-green already in production compose")
    if (SRC / "docker-compose.yml").exists():
        raise SystemExit("refuse: do not upload a whole compose file")

    nginx_dir = ROOT / "ops/nginx"
    nginx_dir.mkdir(parents=True, exist_ok=True)
    ops = ROOT / "ops/compose"
    ops.mkdir(parents=True, exist_ok=True)

    shutil.copy2(SRC / "api-green-stage10.fragment.yml", ops / "api-green-stage10.fragment.yml")
    shutil.copy2(SRC / "api-green-sidecar.conf", nginx_dir / "api-green-sidecar.conf")
    for name in (
        "backup_stage10.py",
        "insert_api_green_stage10.py",
        "deploy_stage10.py",
        "stage10_prod_checks.py",
    ):
        src = SRC / name
        if src.exists():
            shutil.copy2(src, ops / name)

    print(run(["python3", str(ops / "backup_stage10.py")]))
    print(run(["python3", str(ops / "insert_api_green_stage10.py")]))

    before = run(
        [
            "docker",
            "inspect",
            "-f",
            "{{.Id}} {{.State.StartedAt}}",
            "eris-api",
        ]
    )
    print("api_before", before)

    run(
        [
            "docker",
            "compose",
            "-f",
            str(ROOT / "docker-compose.yml"),
            "--profile",
            "bluegreen",
            "up",
            "-d",
            "--build",
            "api-green",
        ]
    )

    deadline = time.time() + 180
    last = ""
    while time.time() < deadline:
        proc = subprocess.run(
            ["curl", "-sS", "--max-time", "5", "http://127.0.0.1:8003/health"],
            capture_output=True,
            text=True,
        )
        last = (proc.stdout or "").strip()
        if '"process_role":"api"' in last.replace(" ", "") or '"process_role": "api"' in last:
            print("green_health", last)
            break
        time.sleep(2)
    else:
        raise SystemExit(f"api-green did not become ready: {last}")

    after = run(
        [
            "docker",
            "inspect",
            "-f",
            "{{.Id}} {{.State.StartedAt}}",
            "eris-api",
        ]
    )
    print("api_after", after)
    if after != before:
        raise SystemExit("refuse/alert: main API container changed")
    print("stage10 deploy finished; main API unchanged")


if __name__ == "__main__":
    main()
