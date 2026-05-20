# C-15: MTProto security policy gate
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
$envFile = Join-Path $Root ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
        if ($_ -match '^\s*([^#=]+)=(.*)$') {
            Set-Item -Path "env:$($Matches[1].Trim())" -Value $Matches[2].Trim().Trim('"').Trim("'") -ErrorAction SilentlyContinue
        }
    }
}
$py = Join-Path $Root ".tools\python312\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$env:PYTHONPATH = Join-Path $Root "app"
& $py -c "from services.mtproto.security_policy import check_production_session_policy; import sys; i=check_production_session_policy(); sys.exit(1 if i else 0)"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py -m pytest (Join-Path $Root "tests\test_mtproto_security_c15.py") -q
exit $LASTEXITCODE
