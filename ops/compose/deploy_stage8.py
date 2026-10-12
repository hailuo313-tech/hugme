"""Install Stage 8 files without rebuilding or restarting the main API."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

ROOT = Path("/opt/eris")
SRC = Path("/tmp/stage8-upload")


def run(args: list[str]) -> str:
    print("+", " ".join(args))
    return subprocess.check_output(args, text=True).strip()


def main() -> None:
    if (ROOT / "app/services/runtime_legacy_shutdown.py").exists():
        raise SystemExit("refuse: stage 9 shutdown module is present")

    backup = run(["python3", str(SRC / "backup_stage8.py")])
    print("backup", backup)

    dest_canary = ROOT / "app/services/runtime_canary.py"
    shutil.copy2(SRC / "runtime_canary.py", dest_canary)
    print("installed", dest_canary)

    ops = ROOT / "ops/compose"
    ops.mkdir(parents=True, exist_ok=True)
    for name in ("backup_stage8.py", "patch_runtime_split_stage8.py", "verify_stage8_canary.py", "deploy_stage8.py"):
        src = SRC / name
        if src.exists():
            shutil.copy2(src, ops / name)
            print("installed", ops / name)

    tests = ROOT / "tests"
    if tests.exists() and (SRC / "check_runtime_split_stage8.js").exists():
        shutil.copy2(SRC / "check_runtime_split_stage8.js", tests / "check_runtime_split_stage8.js")
        print("installed", tests / "check_runtime_split_stage8.js")

    print(run(["python3", str(ops / "patch_runtime_split_stage8.py")]))

    run(["docker", "cp", str(dest_canary), "eris-api:/app/services/runtime_canary.py"])
    run(
        [
            "docker",
            "cp",
            str(ops / "verify_stage8_canary.py"),
            "eris-api:/tmp/verify_stage8_canary.py",
        ]
    )
    print(
        run(
            [
                "docker",
                "compose",
                "-f",
                str(ROOT / "docker-compose.yml"),
                "exec",
                "-T",
                "-e",
                "PYTHONPATH=/app",
                "-w",
                "/app",
                "api",
                "python",
                "/tmp/verify_stage8_canary.py",
            ]
        )
    )
    print("stage8 deploy finished without compose up")


if __name__ == "__main__":
    main()
