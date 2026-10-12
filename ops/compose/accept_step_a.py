"""Accept Step A after the main API rebuild. Does not start Runtime."""

from __future__ import annotations

from pathlib import Path
import subprocess

ROOT = Path("/opt/eris")


def run(args: list[str]) -> str:
    print("+", " ".join(args))
    return subprocess.check_output(args, text=True).strip()


def exec_api(script_host: Path, script_container: str) -> str:
    run(["docker", "cp", str(script_host), f"eris-api:{script_container}"])
    return run(
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
            script_container,
        ]
    )


def main() -> None:
    ops = ROOT / "ops/compose"
    print(run(["python3", str(ops / "wait_step_a_sessions.py")]))
    print(exec_api(ops / "verify_step_a_hold.py", "/tmp/verify_step_a_hold.py"))
    print(exec_api(ops / "probe_step_a.py", "/tmp/probe_step_a.py"))
    print(run(["python3", str(ops / "wait_step_a_sessions.py")]))
    health = run(["curl", "-sS", "--max-time", "8", "http://127.0.0.1:8000/health"])
    print("health", health)
    after = run(
        ["docker", "inspect", "-f", "{{.Id}} {{.State.StartedAt}} {{.State.Health.Status}}", "eris-api"]
    )
    print("api", after)
    logs = subprocess.run(
        ["docker", "logs", "--since", "20m", "eris-api"],
        capture_output=True,
        text=True,
    )
    combined = (logs.stdout or "") + (logs.stderr or "")
    dup = combined.count("AuthKeyDuplicated")
    print("AuthKeyDuplicated", dup)
    if dup:
        raise SystemExit("AuthKeyDuplicated appeared after Step A")
    print("stepA accepted")


if __name__ == "__main__":
    main()
