"""Install Stage 9 files without rebuilding or stopping Legacy."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

ROOT = Path("/opt/eris")
SRC = Path("/tmp/stage9-upload")


def run(args: list[str]) -> str:
    print("+", " ".join(args))
    return subprocess.check_output(args, text=True).strip()


def main() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    if "\n  api-green:" in compose:
        raise SystemExit("refuse: production compose has api-green")
    if (SRC / "docker-compose.yml").exists():
        raise SystemExit("refuse: do not upload a whole compose file")

    backup = run(["python3", str(SRC / "backup_stage9.py")])
    print("backup", backup)

    dest = ROOT / "app/services/runtime_legacy_shutdown.py"
    shutil.copy2(SRC / "runtime_legacy_shutdown.py", dest)
    print("installed", dest)

    ops = ROOT / "ops/compose"
    ops.mkdir(parents=True, exist_ok=True)
    for name in (
        "backup_stage9.py",
        "patch_runtime_split_stage9.py",
        "verify_stage9_shutdown.py",
        "deploy_stage9.py",
        "stage9_prod_checks.py",
    ):
        src = SRC / name
        if src.exists():
            shutil.copy2(src, ops / name)
            print("installed", ops / name)

    tests = ROOT / "tests"
    if tests.exists() and (SRC / "check_runtime_split_stage9.js").exists():
        shutil.copy2(SRC / "check_runtime_split_stage9.js", tests / "check_runtime_split_stage9.js")
        print("installed", tests / "check_runtime_split_stage9.js")

    print(run(["python3", str(ops / "patch_runtime_split_stage9.py")]))

    run(["docker", "cp", str(dest), "eris-api:/app/services/runtime_legacy_shutdown.py"])
    run(
        [
            "docker",
            "cp",
            str(ops / "verify_stage9_shutdown.py"),
            "eris-api:/tmp/verify_stage9_shutdown.py",
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
                "/tmp/verify_stage9_shutdown.py",
            ]
        )
    )
    print("stage9 deploy finished without compose up")


if __name__ == "__main__":
    main()
