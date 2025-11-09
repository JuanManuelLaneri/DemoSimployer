#!/bin/bash
# Project Chimera - Linux/Mac Test Helper
#
# This script runs tests on Linux/Mac using testcontainers.
# Testcontainers will automatically start RabbitMQ in Docker.
#
# Usage:
#   ./test-linux.sh              # Run all tests
#   ./test-linux.sh --quick      # Run quick tests only (no Docker)
#   ./test-linux.sh --coverage   # Run with coverage report
#   ./test-linux.sh --help       # Show help

set -e  # Exit on error

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
NC='\033[0m' # No Color

# Print with color
print_header() {
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${CYAN}========================================${NC}"
    echo ""
}

print_info() {
    echo -e "${CYAN}[INFO] $1${NC}"
}

print_success() {
    echo -e "${GREEN}[SUCCESS] $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}[WARNING] $1${NC}"
}

print_error() {
    echo -e "${RED}[ERROR] $1${NC}"
}

# Parse arguments
QUICK=false
COVERAGE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --quick|-q)
            QUICK=true
            shift
            ;;
        --coverage|-c)
            COVERAGE=true
            shift
            ;;
        --help|-h)
            echo "Project Chimera - Test Helper"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --quick, -q      Run quick tests only (no Docker)"
            echo "  --coverage, -c   Run with coverage report"
            echo "  --help, -h       Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                  # Run all tests"
            echo "  $0 --quick          # Run quick tests"
            echo "  $0 --coverage       # Run with coverage"
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

print_header "Project Chimera - Linux/Mac Test Helper"

# Quick test mode
if [ "$QUICK" = true ]; then
    print_info "Running quick tests (no Docker)..."
    echo ""

    print_info "Schema validation tests..."
    pytest tests/integration/test_schemas.py -v

    echo ""
    print_info "E2E configuration tests..."
    pytest tests/integration/test_e2e.py -v

    echo ""
    print_info "LLM client tests..."
    pytest tests/integration/test_llm_client.py -v

    echo ""
    print_success "Quick tests complete!"
    exit 0
fi

# Full test mode
print_info "Running full integration tests..."
print_info "Testcontainers will automatically start RabbitMQ in Docker"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    print_error "Docker is not running!"
    echo ""
    echo "Please start Docker and try again:"
    echo "  - Linux: sudo systemctl start docker"
    echo "  - Mac: Start Docker.app from Applications"
    exit 1
fi

print_success "Docker is running"
echo ""

# Check if in virtual environment
if [ -z "$VIRTUAL_ENV" ]; then
    print_warning "Not in a virtual environment"
    print_info "Recommended: source .venv/bin/activate"
    echo ""
fi

# Run tests
print_info "Running tests..."
echo ""

if [ "$COVERAGE" = true ]; then
    print_info "Running with coverage report..."
    pytest tests/integration/ -v --cov --cov-report=html --cov-report=term
else
    pytest tests/integration/ -v
fi

TEST_RESULT=$?

echo ""
if [ $TEST_RESULT -eq 0 ]; then
    print_success "All tests passed!"
else
    print_warning "Some tests failed. Exit code: $TEST_RESULT"
fi

echo ""
print_header "Test run complete!"

exit $TEST_RESULT
