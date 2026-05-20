# C-11: UX walkthrough artifact gate
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$required = @(
  "admin/lib/priorityDisplay.ts",
  "admin/hooks/useOperatorTaskWs.ts",
  "admin/components/OperatorWsStatus.tsx",
  "docs/C11_UX_ISSUES.md",
  "docs/C11_INSPECTION_REPORT.md",
  "fixtures/c11_ux_checklist.json"
)

foreach ($f in $required) {
  if (-not (Test-Path (Join-Path $Root $f))) {
    Write-Error "Missing $f"
  }
}

$page = Get-Content (Join-Path $Root "admin/app/page.tsx") -Raw
$patterns = @(
  "OperatorWsStatus",
  "vipToLevelTier",
  "WAITING_OPERATOR",
  "closeDetail",
  'setState("WAITING_OPERATOR")'
)
foreach ($p in $patterns) {
  if ($page -notmatch [regex]::Escape($p)) {
    Write-Error "page.tsx missing pattern: $p"
  }
}

$issues = Get-Content (Join-Path $Root "docs/C11_UX_ISSUES.md") -Raw
if ($issues -notmatch "UX-01") {
  Write-Error "C11_UX_ISSUES.md missing issue registry"
}

Write-Host "C-11 UX walkthrough gate: PASS"
exit 0
