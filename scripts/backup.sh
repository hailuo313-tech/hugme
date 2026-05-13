#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/opt/eris}"
BACKUP_DIR="${BACKUP_DIR:-/opt/eris/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-eris-postgres}"
POSTGRES_DB="${POSTGRES_DB:-eris}"
POSTGRES_USER="${POSTGRES_USER:-eris}"
REDIS_CONTAINER="${REDIS_CONTAINER:-eris-redis}"
CRON_FILE="${CRON_FILE:-/etc/cron.d/eris-backup}"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
work_dir="${BACKUP_DIR}/.work-${timestamp}"
archive="${BACKUP_DIR}/eris_backup_${timestamp}.tar.gz"
log_file="${BACKUP_DIR}/backup.log"

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

load_env() {
  if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${PROJECT_ROOT}/.env"
    set +a
  fi
  POSTGRES_DB="${POSTGRES_DB:-eris}"
  POSTGRES_USER="${POSTGRES_USER:-eris}"
  REDIS_PASSWORD="${REDIS_PASSWORD:-redis_secret_2026}"
}

install_cron() {
  mkdir -p "$BACKUP_DIR"
  cat >"$CRON_FILE" <<EOF
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

0 0 * * * root cd ${PROJECT_ROOT} && PROJECT_ROOT=${PROJECT_ROOT} BACKUP_DIR=${BACKUP_DIR} ${PROJECT_ROOT}/scripts/backup.sh >> ${log_file} 2>&1
EOF
  chmod 0644 "$CRON_FILE"
  log "installed cron: $CRON_FILE"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "missing required command: $1"
    exit 1
  fi
}

run_backup() {
  require_command docker
  require_command tar

  load_env
  mkdir -p "$BACKUP_DIR" "$work_dir"

  log "starting ERIS backup into $archive"

  docker exec "$POSTGRES_CONTAINER" pg_dump \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    --format=custom \
    --no-owner \
    --no-privileges \
    >"${work_dir}/postgres.dump"

  docker exec "$POSTGRES_CONTAINER" pg_dump \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    --format=plain \
    --no-owner \
    --no-privileges \
    >"${work_dir}/postgres.sql"

  docker exec "$REDIS_CONTAINER" redis-cli \
    --pass "$REDIS_PASSWORD" \
    SAVE >/dev/null
  docker cp "${REDIS_CONTAINER}:/data/dump.rdb" "${work_dir}/redis.rdb"

  git -C "$PROJECT_ROOT" rev-parse HEAD >"${work_dir}/git_head.txt" 2>/dev/null || true
  git -C "$PROJECT_ROOT" status --short >"${work_dir}/git_status.txt" 2>/dev/null || true

  cat >"${work_dir}/manifest.txt" <<EOF
created_at_utc=${timestamp}
project_root=${PROJECT_ROOT}
postgres_container=${POSTGRES_CONTAINER}
postgres_db=${POSTGRES_DB}
postgres_user=${POSTGRES_USER}
redis_container=${REDIS_CONTAINER}
retention_days=${RETENTION_DAYS}
contents=postgres.dump postgres.sql redis.rdb git_head.txt git_status.txt
EOF

  tar -C "$work_dir" -czf "$archive" .
  chmod 0600 "$archive"
  rm -rf "$work_dir"

  find "$BACKUP_DIR" \
    -maxdepth 1 \
    -type f \
    -name 'eris_backup_*.tar.gz' \
    -mtime +"$RETENTION_DAYS" \
    -print \
    -delete

  log "backup complete: $archive"
}

case "${1:-}" in
  --install-cron)
    install_cron
    ;;
  --help|-h)
    cat <<EOF
Usage:
  scripts/backup.sh              Run one backup now.
  scripts/backup.sh --install-cron

Environment overrides:
  PROJECT_ROOT=/opt/eris
  BACKUP_DIR=/opt/eris/backups
  RETENTION_DAYS=7
  POSTGRES_CONTAINER=eris-postgres
  POSTGRES_DB=eris
  POSTGRES_USER=eris
  REDIS_CONTAINER=eris-redis
EOF
    ;;
  *)
    run_backup
    ;;
esac
