#!/usr/bin/env bash
# P5-02: Load test runner script

set -euo pipefail

# Configuration
API_BASE="${API_BASE:-http://127.0.0.1:8000}"
CONCURRENCY="${CONCURRENCY:-1000}"
REQUESTS_PER_ENDPOINT="${REQUESTS_PER_ENDPOINT:-10}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-30}"
OUTPUT_DIR="${OUTPUT_DIR:-scripts/perf/reports}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
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

log_info() {
    printf '${BLUE}[INFO] %s${NC}\n' "$(date +%H:%M:%S) $*"
}

# Check if Python is available
check_python() {
    if ! command -v python3 >/dev/null 2>&1; then
        log_error "Python 3 is not installed or not in PATH"
        return 1
    fi
    return 0
}

# Check if API is accessible
check_api() {
    log_info "Checking API accessibility at $API_BASE..."
    
    local max_retries=10
    local retry=0
    
    while [ $retry -lt $max_retries ]; do
        if curl -fsS "$API_BASE/health" >/dev/null 2>&1; then
            log_success "API is accessible"
            return 0
        fi
        retry=$((retry + 1))
        sleep 2
    done
    
    log_error "API is not accessible within timeout"
    return 1
}

# Run load test
run_load_test() {
    log "Starting P5-02 load test..."
    log "Configuration:"
    log "  API_BASE: $API_BASE"
    log "  CONCURRENCY: $CONCURRENCY"
    log "  REQUESTS_PER_ENDPOINT: $REQUESTS_PER_ENDPOINT"
    log "  TIMEOUT_SECONDS: $TIMEOUT_SECONDS"
    log "  OUTPUT_DIR: $OUTPUT_DIR"
    log ""
    
    # Set environment variables
    export API_BASE="$API_BASE"
    export P5_02_CONCURRENCY="$CONCURRENCY"
    export P5_02_REQUESTS_PER_ENDPOINT="$REQUESTS_PER_ENDPOINT"
    export P5_02_TIMEOUT_SECONDS="$TIMEOUT_SECONDS"
    export P5_02_OUTPUT_DIR="$OUTPUT_DIR"
    
    # Create output directory
    mkdir -p "$OUTPUT_DIR"
    
    # Run Python load test script
    if python3 scripts/perf/p5_02_load_test.py; then
        log_success "Load test completed successfully"
        return 0
    else
        log_error "Load test failed"
        return 1
    fi
}

# Display latest report
display_latest_report() {
    local latest_report
    latest_report=$(find "$OUTPUT_DIR" -name "p5_02_load_test_report_*.json" -type f -printf '%T@ %p\n' | sort -n | tail -1 | cut -d' ' -f2-)
    
    if [ -n "$latest_report" ] && [ -f "$latest_report" ]; then
        log ""
        log_info "Latest report: $latest_report"
        log "Report content:"
        cat "$latest_report"
    else
        log_warning "No report found in $OUTPUT_DIR"
    fi
}

# Main execution
main() {
    log "🚀 P5-02 Load Test Runner"
    log ""
    
    # Check prerequisites
    check_python || exit 1
    check_api || exit 1
    
    # Run load test
    if run_load_test; then
        EXIT_CODE=0
    else
        EXIT_CODE=1
    fi
    
    # Display report
    display_latest_report
    
    # Exit with appropriate code
    if [ $EXIT_CODE -eq 0 ]; then
        log_success "P5-02 load test execution completed successfully"
        exit 0
    else
        log_error "P5-02 load test execution failed"
        exit 1
    fi
}

# Handle script arguments
case "${1:-}" in
    --check-only)
        check_python && check_api
        ;;
    --report-only)
        display_latest_report
        ;;
    *)
        main
        ;;
esac