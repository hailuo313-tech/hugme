# C-13: Grafana/alert walkthrough artifact gate
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$required = @(
  "app/services/grafana_integration.py",
  "scripts/c13_grafana_audit.py",
  "monitoring/alerts/eris-alerts.yml",
  "monitoring/grafana-dashboard-eris-mvp.json",
  "docs/C13_GRAFANA_ISSUES.md",
  "docs/C13_INSPECTION_REPORT.md",
  "docs/C13_GRAFANA_WALKTHROUGH.md",
  "fixtures/c13_grafana_checklist.json"
)

foreach ($f in $required) {
  if (-not (Test-Path (Join-Path $Root $f))) {
    Write-Error "Missing $f"
  }
}

$dash = Get-Content (Join-Path $Root "monitoring/grafana-dashboard-eris-mvp.json") -Raw
foreach ($p in @("LLM Request Rate", "LLM p95 Latency", "ERIS MVP Overview")) {
  if ($dash -notmatch [regex]::Escape($p)) {
    Write-Error "dashboard missing: $p"
  }
}

$issues = Get-Content (Join-Path $Root "docs/C13_GRAFANA_ISSUES.md") -Raw
if ($issues -notmatch "GR-01") {
  Write-Error "C13_GRAFANA_ISSUES.md missing issue registry"
}

$py = Join-Path $Root ".tools\python312\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$env:PYTHONPATH = Join-Path $Root "app"

& $py (Join-Path $Root "scripts\c13_grafana_audit.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $py -m pytest (Join-Path $Root "tests\test_c13_grafana_smoke.py") -q
exit $LASTEXITCODE
