# C-07: script hooks + safety redline gate
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$py = Join-Path $Root ".tools\python312\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$env:PYTHONPATH = Join-Path $Root "app"

& $py (Join-Path $Root "scripts\c07_script_safety_audit.py")
exit $LASTEXITCODE
