#!/usr/bin/env bash
set -euo pipefail

cd /opt/eris

git fetch --tags origin

current="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$current" != "main" ]]; then
  echo "REFUSING: deploy must run on main (current=$current)" >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "REFUSING: dirty working tree" >&2
  git status --short >&2
  exit 1
fi

git pull --ff-only origin main

# Production strict mode: uncomment when every deploy must be exactly tagged.
# if ! git describe --exact-match --tags HEAD >/dev/null 2>&1; then
#   echo "REFUSING: HEAD must be a tagged release" >&2
#   exit 1
# fi

docker compose up -d --build api
sleep 5
curl -fsS http://127.0.0.1:8000/health/detail
echo "DEPLOY OK at $(git rev-parse --short HEAD)"
