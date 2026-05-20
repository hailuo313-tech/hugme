# C-06: J-01 level grading smoke (10/10 fixtures)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$py = Join-Path $Root ".tools\python312\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$env:PYTHONPATH = Join-Path $Root "app"

& $py (Join-Path $Root "scripts\j01_level_smoke.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $py -m pytest (Join-Path $Root "tests\test_j01_level_smoke.py") -q
exit $LASTEXITCODE
