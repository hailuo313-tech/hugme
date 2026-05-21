#!/usr/bin/env bash
# P5-01: E2E test script for MTProto inbound → AI → human-like delivery → archiving

set -euo pipefail

# Configuration
API_BASE="${API_BASE:-http://127.0.0.1:8000}"
DB_CONTAINER="${DB_CONTAINER:-eris-postgres}"
DB_USER="${DB_USER:-eris}"
DB_NAME="${DB_NAME:-eris}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"
}

log_error() {
    printf '${RED}[ERROR] %s${NC}\n' "$(date +%H:%M:%S) $*"
}

log_success() {
    printf '${GREEN}[SUCCESS] %s${NC}\n' "$(date +%H:%M:%S) $*"
}

log_warning() {
    printf '${YELLOW}[WARNING] %s${NC}\n' "$(date +%H:%M:%S) $*"
}

# Check if docker is available
check_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        log_error "Docker is not installed or not in PATH"
        return 1
    fi
    return 0
}

# Check if database container is running
check_db_container() {
    if ! docker ps --format '{{.Names}}' | grep -qx "$DB_CONTAINER"; then
        log_error "Database container $DB_CONTAINER is not running"
        return 1
    fi
    return 0
}

# Wait for API to be healthy
wait_for_api() {
    local max_retries=30
    local retry=0
    
    log "Waiting for API to be healthy at $API_BASE..."
    
    while [ $retry -lt $max_retries ]; do
        if curl -fsS "$API_BASE/health/detail" | grep -q '"api":"ok"'; then
            log_success "API is healthy"
            return 0
        fi
        retry=$((retry + 1))
        sleep 2
    done
    
    log_error "API did not become healthy within timeout"
    return 1
}

# Run database query
db_query() {
    local sql="$1"
    docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -Atqc "$sql" 2>/dev/null || echo "NO_DB_CLIENT"
}

# Setup test environment
setup_environment() {
    log "Setting up test environment..."
    
    # Check prerequisites
    check_docker || exit 1
    check_db_container || exit 1
    wait_for_api || exit 1
    
    # Verify script templates exist
    local script_count
    script_count=$(db_query "SELECT COUNT(*) FROM script_templates WHERE is_active = true;")
    
    if [ "$script_count" = "NO_DB_CLIENT" ] || [ -z "$script_count" ] || [ "$script_count" -eq 0 ]; then
        log_warning "No active script templates found. Tests may fail."
    else
        log_success "Found $script_count active script templates"
    fi
}

# Run P5-01 E2E tests
run_tests() {
    log "Running P5-01 E2E tests..."
    
    local test_dir
    test_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
    
    cd "$test_dir" || exit 1
    
    # Set environment for tests
    export PYTHONPATH="${PYTHONPATH:-app}"
    export API_BASE="$API_BASE"
    export DB_CONTAINER="$DB_CONTAINER"
    export DB_USER="$DB_USER"
    export DB_NAME="$DB_NAME"
    
    # Run pytest with P5-01 tests
    if $PYTHON_BIN -m pytest tests/test_p5_01_e2e_mtproto_ai_archive.py -v -s --tb=short; then
        log_success "P5-01 E2E tests passed"
        return 0
    else
        log_error "P5-01 E2E tests failed"
        return 1
    fi
}

# Cleanup test data
cleanup() {
    log "Cleaning up test data..."
    
    # Clean up test users created during the test
    local cleanup_sql
    cleanup_sql="DELETE FROM users WHERE external_id LIKE 'tg_test_p5_01_%' OR username LIKE 'p5_01_test_%';"
    
    if db_query "$cleanup_sql"; then
        log_success "Test data cleaned up"
    else
        log_warning "Failed to clean up test data"
    fi
}

# Main execution
main() {
    log "Starting P5-01 E2E test execution..."
    log "API_BASE: $API_BASE"
    log "DB_CONTAINER: $DB_CONTAINER"
    
    # Setup environment
    setup_environment
    
    # Run tests
    if run_tests; then
        EXIT_CODE=0
    else
        EXIT_CODE=1
    fi
    
    # Cleanup
    cleanup
    
    # Exit with appropriate code
    if [ $EXIT_CODE -eq 0 ]; then
        log_success "P5-01 E2E test execution completed successfully"
        exit 0
    else
        log_error "P5-01 E2E test execution failed"
        exit 1
    fi
}

# Handle script arguments
case "${1:-}" in
    --skip-cleanup)
        log "Skipping cleanup as requested"
        setup_environment && run_tests
        ;;
    --cleanup-only)
        setup_environment && cleanup
        ;;
    *)
        main
        ;;
esac