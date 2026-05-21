# C-05: level_engine tests + branch coverage gate
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$py = Join-Path $Root ".tools\python312\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$env:PYTHONPATH = Join-Path $Root "app"

& $py -m pip install -q pytest pytest-cov 2>$null
& $py -m pytest `
  (Join-Path $Root "tests\test_level_engine.py") `
  (Join-Path $Root "tests\test_p2_08_level_engine_case_gate.py") `
  -q `
  --cov=services.level_engine `
  --cov-branch `
  --cov-fail-under=85 `
  --cov-report=term-missing:skip-covered
exit $LASTEXITCODE
