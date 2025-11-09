# Project Chimera - Windows Test Helper
#
# This script makes it easy to run tests on Windows by:
# 1. Starting RabbitMQ in Docker
# 2. Setting environment variables
# 3. Running pytest
# 4. Cleaning up afterwards
#
# Usage:
#   .\test-windows.ps1              # Run all tests
#   .\test-windows.ps1 -Quick       # Run quick tests only (no Docker)
#   .\test-windows.ps1 -Coverage    # Run with coverage report
#   .\test-windows.ps1 -Cleanup     # Stop RabbitMQ and cleanup

param(
    [switch]$Quick,
    [switch]$Coverage,
    [switch]$Cleanup
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Project Chimera - Windows Test Helper" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Cleanup mode
if ($Cleanup) {
    Write-Host "[CLEANUP] Stopping test RabbitMQ..." -ForegroundColor Yellow
    docker-compose -f docker-compose.test.yml down -v
    Write-Host "[CLEANUP] Done!" -ForegroundColor Green
    exit 0
}

# Quick test mode (no Docker)
if ($Quick) {
    Write-Host "[QUICK TEST] Running tests without Docker..." -ForegroundColor Yellow
    Write-Host ""

    Write-Host "[TEST] Schema validation tests..." -ForegroundColor Cyan
    pytest tests/integration/test_schemas.py -v

    Write-Host ""
    Write-Host "[TEST] E2E configuration tests..." -ForegroundColor Cyan
    pytest tests/integration/test_e2e.py -v

    Write-Host ""
    Write-Host "[TEST] LLM client tests..." -ForegroundColor Cyan
    pytest tests/integration/test_llm_client.py -v

    Write-Host ""
    Write-Host "[QUICK TEST] Complete!" -ForegroundColor Green
    exit 0
}

# Full test mode (with Docker)
Write-Host "[SETUP] Starting RabbitMQ for testing..." -ForegroundColor Yellow
docker-compose -f docker-compose.test.yml up -d

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Failed to start RabbitMQ. Is Docker Desktop running?" -ForegroundColor Red
    exit 1
}

Write-Host "[SETUP] Waiting for RabbitMQ to be ready..." -ForegroundColor Yellow
Start-Sleep -Seconds 10

Write-Host "[SETUP] Checking RabbitMQ health..." -ForegroundColor Yellow
$healthCheck = docker ps --filter "name=chimera-test-rabbitmq" --filter "health=healthy" --format "{{.Names}}"

if ($healthCheck -eq "chimera-test-rabbitmq") {
    Write-Host "[SETUP] RabbitMQ is healthy!" -ForegroundColor Green
} else {
    Write-Host "[WARNING] RabbitMQ might not be fully ready. Waiting 5 more seconds..." -ForegroundColor Yellow
    Start-Sleep -Seconds 5
}

Write-Host ""
Write-Host "[SETUP] Setting environment variables..." -ForegroundColor Yellow
$env:RABBITMQ_HOST = "localhost"
$env:RABBITMQ_PORT = "5672"
$env:RABBITMQ_USER = "guest"
$env:RABBITMQ_PASS = "guest"

Write-Host "[INFO] RABBITMQ_HOST=$env:RABBITMQ_HOST" -ForegroundColor Gray
Write-Host ""

# Run tests
Write-Host "[TEST] Running integration tests..." -ForegroundColor Cyan
Write-Host ""

if ($Coverage) {
    Write-Host "[TEST] Running with coverage..." -ForegroundColor Cyan
    pytest tests/integration/ -v --cov --cov-report=html --cov-report=term
} else {
    pytest tests/integration/ -v
}

$testResult = $LASTEXITCODE

Write-Host ""
if ($testResult -eq 0) {
    Write-Host "[SUCCESS] All tests passed!" -ForegroundColor Green
} else {
    Write-Host "[WARNING] Some tests failed. Exit code: $testResult" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "[CLEANUP] Stopping RabbitMQ..." -ForegroundColor Yellow
docker-compose -f docker-compose.test.yml down

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Test run complete!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

exit $testResult
