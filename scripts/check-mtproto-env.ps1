# C-03: verify MTProto-related vars in .env
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$envFile = Join-Path $Root ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
        if ($_ -match '^\s*([^#=]+)=(.*)$') {
            $name = $Matches[1].Trim()
            $value = $Matches[2].Trim().Trim('"').Trim("'")
            Set-Item -Path "env:$name" -Value $value -ErrorAction SilentlyContinue
        }
    }
}

$py = Join-Path $Root ".tools\python312\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$env:PYTHONPATH = Join-Path $Root "app"

& $py -c @"
import sys
from core.mtproto_env import mtproto_env_status
ok, issues = mtproto_env_status()
if ok:
    print('MTProto env OK (C-03 checklist passed).')
    sys.exit(0)
print('MTProto env incomplete:')
for i in issues:
    print('  -', i)
print()
print('See docs/MTProto_ENV_SETUP.md and .env.template')
sys.exit(1)
"@

exit $LASTEXITCODE
