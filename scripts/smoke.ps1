# Phase 1 vertical-slice smoke test (Windows / PowerShell).
#
# 1. starts the ingestion service (OTLP/gRPC on :4317)
# 2. runs the instrumented example agent
# 3. runs `stethoscope list-traces` and asserts a trace was captured
#
# Requires: Rust toolchain built, stethoscope-py installed
#   (pip install -e packages/sdk-python).

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$db = Join-Path $env:TEMP "stethoscope-smoke\traces.db"
New-Item -ItemType Directory -Force (Split-Path $db) | Out-Null
if (Test-Path $db) { Remove-Item $db -Force }

Write-Host "[smoke] starting ingestion service..."
$svc = Start-Process -PassThru -NoNewWindow `
    -FilePath "cargo" `
    -ArgumentList @("run", "-q", "-p", "stethoscope-cli", "--", "serve", "--db", $db)
try {
    Start-Sleep -Seconds 3   # let the gRPC server bind

    Write-Host "[smoke] running instrumented agent..."
    $env:STETHOSCOPE_ENDPOINT = "127.0.0.1:4317"
    python examples/min_agent/agent.py
    Start-Sleep -Seconds 2   # let the batch exporter flush

    Write-Host "[smoke] listing traces..."
    $out = & cargo run -q -p stethoscope-cli -- list-traces --db $db | Out-String
    Write-Host $out

    if ($out -match "support-bot" -and $out -match "trace\(s\)\.") {
        Write-Host "[smoke] PASS" -ForegroundColor Green
        exit 0
    }
    Write-Host "[smoke] FAIL: no trace captured" -ForegroundColor Red
    exit 1
}
finally {
    if ($svc -and -not $svc.HasExited) { Stop-Process -Id $svc.Id -Force }
}
