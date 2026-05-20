# C-12: E2E/CI nightly artifact gate
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$required = @(
  "app/services/e2e_ci_integration.py",
  "scripts/e2e/smoke.sh",
  "scripts/c12_e2e_ci_audit.py",
  ".github/workflows/nightly-e2e-ci.yml",
  "docs/C12_E2E_CI_REVIEW.md",
  "docs/C12_INSPECTION_REPORT.md",
  "fixtures/c12_e2e_ci_checklist.json",
  "fixtures/c12_nightly_stability.json"
)

foreach ($f in $required) {
  if (-not (Test-Path (Join-Path $Root $f))) {
    Write-Error "Missing $f"
  }
}

$run = Get-Content (Join-Path $Root "scripts/e2e/run.sh") -Raw
foreach ($p in @("E2E_CHAT_ROUNDS", "E2E_SKIP_STRIPE", "handoff lock API")) {
  if ($run -notmatch [regex]::Escape($p)) {
    Write-Error "run.sh missing pattern: $p"
  }
}

$py = Join-Path $Root ".tools\python312\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$env:PYTHONPATH = Join-Path $Root "app"

& $py (Join-Path $Root "scripts\c12_e2e_ci_audit.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $py -m pytest (Join-Path $Root "tests\test_c12_e2e_ci_smoke.py") -q
exit $LASTEXITCODE
