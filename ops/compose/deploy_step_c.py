"""Install Step C switcher without rebuilding any container."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

ROOT = Path("/opt/eris")
SRC = Path("/tmp/step-c-upload")


def run(args: list[str]) -> str:
    print("+", " ".join(args))
    return subprocess.check_output(args, text=True).strip()


def main() -> None:
    if (SRC / "docker-compose.yml").exists():
        raise SystemExit("refuse: do not upload a whole compose file")
    ops = ROOT / "ops/compose"
    ops.mkdir(parents=True, exist_ok=True)
    for name in (
        "backup_step_c.py",
        "deploy_step_c.py",
        "probe_step_c.py",
        "accept_step_c.py",
    ):
        src = SRC / name
        if src.exists():
            shutil.copy2(src, ops / name)
            print("installed", ops / name)

    module = SRC / "runtime_account_switch.py"
    if not module.exists():
        raise SystemExit("missing runtime_account_switch.py")
    dest = ROOT / "app/services/runtime_account_switch.py"
    shutil.copy2(module, dest)
    print("installed", dest)

    before = run(["docker", "inspect", "-f", "{{.Id}} {{.State.StartedAt}}", "eris-api"])
    print("api_before", before)
    Path("/tmp/step-c-api-before.txt").write_text(before + "\n", encoding="utf-8")

    print(run(["python3", str(ops / "backup_step_c.py")]))
    run(["docker", "cp", str(dest), "eris-api:/app/services/runtime_account_switch.py"])
    run(["docker", "cp", str(dest), "eris-telegram-runtime:/app/services/runtime_account_switch.py"])
    after = run(["docker", "inspect", "-f", "{{.Id}} {{.State.StartedAt}}", "eris-api"])
    if after != before:
        raise SystemExit("refuse: main API container changed")
    print("stepC deploy finished without compose up")


if __name__ == "__main__":
    main()
