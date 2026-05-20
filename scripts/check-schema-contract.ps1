# C-04: schema_spec.json + inbound contract gate
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$py = Join-Path $Root ".tools\python312\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$env:PYTHONPATH = Join-Path $Root "app"

& $py -m pip install -q jsonschema pytest 2>$null
& $py -m pytest (Join-Path $Root "tests\test_schema_spec_c04.py") -q
exit $LASTEXITCODE
