# Open business-flow.html locally (UTF-8 without BOM)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Src = Join-Path $Root "docs\product\business-flow.html"
$Tmp = Join-Path $env:TEMP "eris-business-flow-preview.html"

$content = [System.IO.File]::ReadAllText($Src)
if ($content.Length -gt 0 -and [int][char]$content[0] -eq 0xFEFF) {
  $content = $content.Substring(1)
}
$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($Tmp, $content, $utf8)

$py = Join-Path $Root ".tools\python312\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$env:PYTHONPATH = $Root
& node (Join-Path $Root "scripts\check-bf-html.js") $Tmp
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Opening $Tmp"
Start-Process $Tmp
