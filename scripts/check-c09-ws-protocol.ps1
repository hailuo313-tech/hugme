# C-09: WebSocket protocol conformance
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$py = Join-Path $Root ".tools\python312\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$env:PYTHONPATH = Join-Path $Root "app"

& $py (Join-Path $Root "scripts\c09_ws_protocol_audit.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $py -m pytest (Join-Path $Root "tests\test_c09_ws_protocol.py") (Join-Path $Root "tests\test_realtime.py") -q
exit $LASTEXITCODE
