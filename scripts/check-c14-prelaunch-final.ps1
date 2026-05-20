# C-14: pre-launch final inspection gate
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$required = @(
  "app/services/prelaunch_integration.py",
  "app/services/grafana_integration.py",
  "scripts/c14_prelaunch_audit.py",
  "scripts/c13_grafana_audit.py",
  "docs/C14_PRELAUNCH_FINAL_REVIEW.md",
  "docs/C14_PRELAUNCH_ISSUES.md",
  "docs/C14_INSPECTION_REPORT.md",
  "docs/C13_INSPECTION_REPORT.md",
  "fixtures/c14_prelaunch_checklist.json",
  "monitoring/grafana-dashboard-eris-mvp.json"
)

foreach ($f in $required) {
  if (-not (Test-Path (Join-Path $Root $f))) {
    Write-Error "Missing $f"
  }
}

$py = Join-Path $Root ".tools\python312\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$env:PYTHONPATH = Join-Path $Root "app"

& $py (Join-Path $Root "scripts\c13_grafana_audit.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $py (Join-Path $Root "scripts\c14_prelaunch_audit.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $py -m pytest (Join-Path $Root "tests\test_c14_prelaunch_smoke.py") (Join-Path $Root "tests\test_c13_grafana_smoke.py") -q
exit $LASTEXITCODE
