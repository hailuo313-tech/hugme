#!/usr/bin/env bash
# P5-04: WebSocket stability test runner script

set -euo pipefail

# Configuration
WS_URL="${WS_URL:-ws://127.0.0.1:8000/ws/operators/tasks}"
OPERATOR_ID="${OPERATOR_ID:-test_p5_04_operator}"
TEST_DURATION_HOURS="${TEST_DURATION_HOURS:-72}"
PING_INTERVAL="${PING_INTERVAL:-30}"
REPORT_INTERVAL="${REPORT_INTERVAL:-3600}"
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
    
    # Check if websockets is installed
    if ! python3 -c "import websockets" 2>/dev/null; then
        log_info "Installing websockets package..."
        pip3 install websockets
    fi
    
    return 0
}

# Check if WebSocket endpoint is accessible
check_websocket() {
    log_info "Checking WebSocket endpoint accessibility at $WS_URL..."
    
    # Simple connectivity check (try to connect and disconnect quickly)
    timeout 5 python3 -c "
import asyncio
import websockets

async def check():
    try:
        async with websockets.connect('$WS_URL', timeout=3) as ws:
            return True
    except Exception as e:
        return False

result = asyncio.run(check())
exit(0 if result else 1)
" 2>/dev/null || {
        log_warning "WebSocket endpoint not immediately accessible (may be normal if service not running)"
        log_info "Test will attempt to connect and retry automatically"
    }
    
    return 0
}

# Run stability test
run_stability_test() {
    log "🚀 Starting P5-04 WebSocket Stability Test"
    log "Configuration:"
    log "  WS_URL: $WS_URL"
    log "  OPERATOR_ID: $OPERATOR_ID"
    log "  TEST_DURATION_HOURS: $TEST_DURATION_HOURS"
    log "  PING_INTERVAL: ${PING_INTERVAL}s"
    log "  REPORT_INTERVAL: ${REPORT_INTERVAL}s"
    log "  OUTPUT_DIR: $OUTPUT_DIR"
    log ""
    
    # Set environment variables
    export WS_URL="$WS_URL"
    export OPERATOR_ID="$OPERATOR_ID"
    export P5_04_TEST_DURATION_HOURS="$TEST_DURATION_HOURS"
    export P5_04_PING_INTERVAL="$PING_INTERVAL"
    export P5_04_REPORT_INTERVAL="$REPORT_INTERVAL"
    export P5_04_OUTPUT_DIR="$OUTPUT_DIR"
    
    # Create output directory
    mkdir -p "$OUTPUT_DIR"
    
    # Run Python stability test script
    if python3 scripts/perf/p5_04_websocket_stability_test.py; then
        log_success "WebSocket stability test completed successfully"
        return 0
    else
        exit_code=$?
        if [ $exit_code -eq 1 ]; then
            log_error "Stability test failed: message loss detected"
        elif [ $exit_code -eq 2 ]; then
            log_warning "Stability test interrupted by user"
        else
            log_error "Stability test failed with error"
        fi
        return $exit_code
    fi
}

# Display latest report
display_latest_report() {
    local latest_report
    latest_report=$(find "$OUTPUT_DIR" -name "p5_04_websocket_stability_report_*.json" -type f -printf '%T@ %p\n' | sort -n | tail -1 | cut -d' ' -f2-)
    
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
    log "🔧 P5-04 WebSocket Stability Test Runner"
    log ""
    
    # Check prerequisites
    check_python || exit 1
    check_websocket || true  # Don't fail on WebSocket check
    
    # Run stability test
    if run_stability_test; then
        EXIT_CODE=0
    else
        EXIT_CODE=$?
    fi
    
    # Display report
    display_latest_report
    
    # Exit with appropriate code
    if [ $EXIT_CODE -eq 0 ]; then
        log_success "P5-04 WebSocket stability test execution completed successfully"
        exit 0
    else
        log_error "P5-04 WebSocket stability test execution failed"
        exit $EXIT_CODE
    fi
}

# Handle script arguments
case "${1:-}" in
    --check-only)
        check_python && check_websocket
        ;;
    --report-only)
        display_latest_report
        ;;
    --short-test)
        # Run a shorter test (1 hour) for quick validation
        TEST_DURATION_HOURS=1
        REPORT_INTERVAL=600  # 10 minutes
        main
        ;;
    *)
        main
        ;;
esac