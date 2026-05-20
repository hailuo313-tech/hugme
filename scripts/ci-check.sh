#!/usr/bin/env bash
# Local mirror of .github/workflows/pr-required-gates.yml (C-02)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "== admin: lint + typecheck + build =="
(cd admin && npm ci && npm run lint && npm run typecheck && npm run build)

echo "== backend: ruff + mypy + compileall + pytest =="
python -m pip install -q -r app/requirements.txt -r requirements-dev.txt
ruff check app tests
ruff format --check app tests
mypy
python -m compileall -q app tests
pytest -q

echo "== ops-guard (subset) =="
test -f docs/REPO_LAYOUT.md
test -f pyproject.toml
echo "CI checks OK"
