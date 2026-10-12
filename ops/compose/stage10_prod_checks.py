"""Stage 10 host-side before/after checks."""

from __future__ import annotations

from pathlib import Path
import hashlib
import subprocess

ROOT = Path("/opt/eris")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(args: list[str]) -> str:
    return subprocess.check_output(args, text=True).strip()


def curl(url: str) -> str:
    proc = subprocess.run(["curl", "-sS", "--max-time", "8", url], capture_output=True, text=True)
    return ((proc.stdout or "") + (proc.stderr or "")).strip()


def main() -> None:
    files = [
        "docker-compose.yml",
        "ops/compose/api-green-stage10.fragment.yml",
        "ops/nginx/api-green-sidecar.conf",
        "ops/nginx/api-next-sidecar.conf",
        "app/main.py",
        ".env",
    ]
    print("=== FILES ===")
    for rel in files:
        path = ROOT / rel
        if path.exists():
            print(f"{rel}\texists=1\tsha={sha256(path)}")
        else:
            print(f"{rel}\texists=0")

    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    print("compose_api_green", int("\n  api-green:" in compose))
    print("compose_bluegreen", int('profiles: ["bluegreen"]' in compose))
    print("compose_green_8003", int("127.0.0.1:8003:8000" in compose))
    print("compose_green_8002", int("eris-api-green" in compose and "8002:8000" in compose.split("api-green:")[-1][:800]))

    print("=== HEALTH 8000 ===")
    print(curl("http://127.0.0.1:8000/health"))
    print("=== HEALTH 8002 ===")
    print(curl("http://127.0.0.1:8002/health"))
    print("=== HEALTH 8003 ===")
    print(curl("http://127.0.0.1:8003/health"))
    print("=== DETAIL 8003 ===")
    print(curl("http://127.0.0.1:8003/health/detail"))

    print("=== DOCKER ===")
    print(
        run(
            [
                "docker",
                "inspect",
                "-f",
                "{{.Id}} {{.State.StartedAt}} {{.State.Status}} {{.State.Health.Status}}",
                "eris-api",
            ]
        )
    )
    print(run(["docker", "compose", "-f", str(ROOT / "docker-compose.yml"), "ps", "--format", "{{.Name}} {{.Status}}"]))
    inspect = subprocess.run(
        ["docker", "inspect", "-f", "{{.Name}} {{.State.Status}}", "eris-api-green"],
        capture_output=True,
        text=True,
    )
    print("green_inspect", ((inspect.stdout or "") + (inspect.stderr or "")).strip())

    print("=== PORTS ===")
    print(run(["bash", "-lc", "ss -lnt | awk 'NR==1 || /:8001 |:8002 |:8003 |:8000 /'"]))

    print("=== LIVE NGINX ===")
    nginx_grep = subprocess.run(
        ["bash", "-lc", "grep -R -n -E '8003|api-green|eris_api_green' /etc/nginx /opt/eris/nginx 2>/dev/null || true"],
        capture_output=True,
        text=True,
    )
    print((nginx_grep.stdout or "").strip() or "no_live_8003")

    print("=== SQL ===")
    sql = (
        "SELECT json_build_object("
        "'accounts', (SELECT json_object_agg(status, cnt) FROM ("
        "SELECT status, count(*)::int AS cnt FROM telegram_accounts GROUP BY status) s),"
        "'ownership', (SELECT count(*)::int FROM telegram_account_ownership)"
        ");"
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
                "postgres",
                "psql",
                "-U",
                "eris",
                "-d",
                "eris",
                "-tA",
                "-c",
                sql,
            ]
        )
    )

    print("=== AUTHKEY ===")
    proc = subprocess.run(["docker", "logs", "--since", "1h", "eris-api"], capture_output=True, text=True)
    logs = (proc.stdout or "") + (proc.stderr or "")
    print("AuthKeyDuplicated", logs.count("AuthKeyDuplicated"))
    green_logs = subprocess.run(["docker", "logs", "--tail", "200", "eris-api-green"], capture_output=True, text=True)
    green_text = (green_logs.stdout or "") + (green_logs.stderr or "")
    print("green_session_manager", green_text.count("session_manager"))
    print("green_connected", green_text.lower().count("successfully restored session"))


if __name__ == "__main__":
    main()
