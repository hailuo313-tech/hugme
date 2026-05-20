# Local mirror of .github/workflows/pr-required-gates.yml (C-02)
# Usage:
#   cd E:\eris
#   .\scripts\ci-check.ps1
#   .\scripts\ci-check.ps1 -AdminOnly
#   .\scripts\ci-check.ps1 -BackendOnly
param(
    [switch]$BackendOnly,
    [switch]$AdminOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$script:PythonCmd = $null

function Require-Command($name) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "Command not found: $name. Install it or add it to PATH."
    }
}

function Test-PythonCandidate {
    param([string[]]$Cmd)
    $exe = $Cmd[0]
    if (-not (Test-Path -LiteralPath $exe -ErrorAction SilentlyContinue)) {
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) {
            return $false
        }
    }
    $pyArgs = @()
    if ($Cmd.Length -gt 1) {
        $pyArgs = $Cmd[1..($Cmd.Length - 1)]
    }
    & $exe @pyArgs -c "import encodings" 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

function Find-WorkingPython {
    $repoPy = Join-Path $Root ".tools\python312\python.exe"
    $candidates = @(
        @($repoPy),
        @("py", "-3.12"),
        @("py", "-3.14"),
        @("py", "-3.11"),
        @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"),
        @("$env:LOCALAPPDATA\Programs\Python\Python314\python.exe")
    )
    foreach ($c in $candidates) {
        $cmd = if ($c -is [string]) { @($c) } else { @($c) }
        if (Test-PythonCandidate $cmd) {
            return $cmd
        }
    }
    $wherePy = @(where.exe python 2>$null)
    foreach ($p in $wherePy) {
        if ($p -match "WindowsApps") { continue }
        if (Test-PythonCandidate @($p)) {
            return @($p)
        }
    }
    return $null
}

function Ensure-Python {
    if ($script:PythonCmd) { return }
    $found = @(Find-WorkingPython)
    if ($found.Count -eq 0) {
        Write-Host ""
        Write-Host "[ERROR] No working Python on this PC (broken install or missing encodings)." -ForegroundColor Red
        Write-Host "Fix: run .\scripts\bootstrap-python.ps1 (portable 3.12 under .tools/)" -ForegroundColor Yellow
        Write-Host "Or reinstall Python 3.12 from https://www.python.org/downloads/ (check Add to PATH)" -ForegroundColor Yellow
        Write-Host "Or run frontend only:  .\scripts\ci-check.ps1 -AdminOnly" -ForegroundColor Yellow
        Write-Host "Backend checks run on GitHub PR job: backend-ci" -ForegroundColor Yellow
        Write-Host ""
        throw "No working Python found."
    }
    $script:PythonCmd = $found
    Write-Host ("Using Python: " + ($found -join " ")) -ForegroundColor DarkGray
}

function Invoke-Py {
    param([string[]]$PyArgs)
    Ensure-Python
    $exe = $script:PythonCmd[0]
    $prefix = @()
    if ($script:PythonCmd.Length -gt 1) {
        $prefix = @($script:PythonCmd[1..($script:PythonCmd.Length - 1)])
    }
    $all = @($prefix) + @($PyArgs)
    & $exe @all
    if ($LASTEXITCODE -ne 0) {
        throw ("Python failed (exit " + $LASTEXITCODE + "): " + ($PyArgs -join " "))
    }
}

function Invoke-Ruff {
    param([string[]]$RuffArgs)
    if (Get-Command ruff -ErrorAction SilentlyContinue) {
        & ruff @RuffArgs
    } else {
        Invoke-Py -PyArgs (@("-m", "ruff") + $RuffArgs)
        return
    }
    if ($LASTEXITCODE -ne 0) {
        throw ("ruff failed (exit " + $LASTEXITCODE + ")")
    }
}

function Invoke-Mypy {
    if (Get-Command mypy -ErrorAction SilentlyContinue) {
        & mypy
    } else {
        Invoke-Py -PyArgs @("-m", "mypy")
        return
    }
    if ($LASTEXITCODE -ne 0) {
        throw ("mypy failed (exit " + $LASTEXITCODE + ")")
    }
}

$env:SECRET_KEY = "ci-test-secret-key"
$env:DATABASE_URL = "postgresql+asyncpg://eris:eris@localhost:5432/eris"
$env:REDIS_URL = "redis://:redis@localhost:6379/0"

if (-not $BackendOnly) {
    Write-Host "== admin: lint + typecheck + build ==" -ForegroundColor Cyan
    Require-Command npm
    Push-Location admin
    try {
        npm ci
        if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
        npm run lint
        if ($LASTEXITCODE -ne 0) { throw "npm run lint failed" }
        npm run typecheck
        if ($LASTEXITCODE -ne 0) { throw "npm run typecheck failed" }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
    } finally {
        Pop-Location
    }
} else {
    Write-Host "== admin: skipped (-BackendOnly) ==" -ForegroundColor Yellow
}

if (-not $AdminOnly) {
    Write-Host "== backend: ruff + mypy + compileall + pytest ==" -ForegroundColor Cyan
    Invoke-Py -PyArgs @("-m", "pip", "install", "-q", "-r", "app/requirements.txt", "-r", "requirements-dev.txt")
    Invoke-Ruff -RuffArgs @("check", "app", "tests")
    Invoke-Ruff -RuffArgs @("format", "--check", "app", "tests")
    Invoke-Mypy
    Invoke-Py -PyArgs @("-m", "compileall", "-q", "app", "tests")
    Invoke-Py -PyArgs @("-m", "pytest", "-q")
} else {
    Write-Host "== backend: skipped (-AdminOnly) ==" -ForegroundColor Yellow
}

Write-Host "== ops-guard (subset) ==" -ForegroundColor Cyan
$requiredFiles = @(
    "docs/REPO_LAYOUT.md",
    "pyproject.toml",
    "docker-compose.yml",
    "RUNBOOK.md"
)
foreach ($f in $requiredFiles) {
    if (-not (Test-Path $f)) {
        throw ("Missing required file: " + $f)
    }
}

Write-Host "CI checks OK" -ForegroundColor Green
