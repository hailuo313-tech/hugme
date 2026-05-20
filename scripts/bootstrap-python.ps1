# Bootstrap portable Python 3.12 under .tools/python312 (Windows)
# Run from repo root:  .\scripts\bootstrap-python.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Tools = Join-Path $Root ".tools"
$Dir = Join-Path $Tools "python312"
$Zip = Join-Path $Tools "python-3.12.10-embed-amd64.zip"
$Py = Join-Path $Dir "python.exe"
$Url = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"

if ((Test-Path $Py) -and (& $Py -c "import encodings" 2>$null; $LASTEXITCODE -eq 0)) {
    Write-Host "Portable Python OK: $Py" -ForegroundColor Green
    exit 0
}

New-Item -ItemType Directory -Force -Path $Tools | Out-Null
if (-not (Test-Path $Zip)) {
    Write-Host "Downloading $Url ..."
    Invoke-WebRequest -Uri $Url -OutFile $Zip -UseBasicParsing
}
if (Test-Path $Dir) { Remove-Item -Recurse -Force $Dir }
Expand-Archive -Path $Zip -DestinationPath $Dir -Force

@(
    "python312.zip",
    ".",
    "Lib\site-packages",
    "",
    "import site"
) | Set-Content -Path (Join-Path $Dir "python312._pth") -Encoding ascii

$GetPip = Join-Path $Tools "get-pip.py"
if (-not (Test-Path $GetPip)) {
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $GetPip -UseBasicParsing
}
& $Py $GetPip
& $Py -m pip install -q -r (Join-Path $Root "app\requirements.txt") -r (Join-Path $Root "requirements-dev.txt")

Write-Host "Done. Run:  .\scripts\ci-check.ps1" -ForegroundColor Green
