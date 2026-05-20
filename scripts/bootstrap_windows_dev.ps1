#Requires -Version 5.1
<#
.SYNOPSIS
    ERIS Windows 开发环境一键引导脚本（D8-DEV-03）

.DESCRIPTION
    1. 检测 Python 3.12（py -3.12 或 python3.12）
    2. 在仓库根目录创建 .venv
    3. 升级 pip
    4. 安装 app\requirements.txt + requirements-dev.txt
    5. 打印 pytest 运行命令

.NOTES
    使用方式（在仓库根目录执行）：
        .\scripts\bootstrap_windows_dev.ps1

    若报"执行策略"错误，以管理员身份运行：
        Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ─── 颜色辅助函数 ──────────────────────────────────────────────────────────────
function Write-Step  { param($msg) Write-Host "`n[STEP] $msg" -ForegroundColor Cyan }
function Write-Ok    { param($msg) Write-Host "  [OK] $msg"   -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Fail  { param($msg) Write-Host "  [FAIL] $msg" -ForegroundColor Red }

# ─── 0. 确认工作目录是仓库根 ──────────────────────────────────────────────────
Write-Step "检查仓库根目录"

$repoRoot = Split-Path -Parent $PSScriptRoot   # scripts/ 的上级即为仓库根
Set-Location $repoRoot
Write-Ok "仓库根目录：$repoRoot"

if (-not (Test-Path "app\requirements.txt")) {
    Write-Fail "当前目录下找不到 app\requirements.txt，请在仓库根目录执行本脚本。"
    exit 1
}
if (-not (Test-Path "requirements-dev.txt")) {
    Write-Fail "当前目录下找不到 requirements-dev.txt，请在仓库根目录执行本脚本。"
    exit 1
}

# ─── 1. 检测 Python 3.12 ──────────────────────────────────────────────────────
Write-Step "检测 Python 3.12"

$python = $null

# 优先尝试 py launcher（Windows 官方安装包自带）
try {
    $ver = & py -3.12 --version 2>&1
    if ($ver -match "Python 3\.12") {
        $python = "py -3.12"
        Write-Ok "找到 py -3.12 → $ver"
    }
} catch { }

# 其次尝试 python3.12（某些手动配 PATH 的场景）
if (-not $python) {
    try {
        $ver = & python3.12 --version 2>&1
        if ($ver -match "Python 3\.12") {
            $python = "python3.12"
            Write-Ok "找到 python3.12 → $ver"
        }
    } catch { }
}

# 最后检查默认 python 是否是 3.12
if (-not $python) {
    try {
        $ver = & python --version 2>&1
        if ($ver -match "Python 3\.12") {
            $python = "python"
            Write-Ok "默认 python → $ver（3.12）"
        } elseif ($ver -match "Python 3\.(1[3-9]|[2-9]\d)") {
            Write-Warn "检测到 $ver，但 >= 3.13 的版本在安装 asyncpg / pydantic-core 时"
            Write-Warn "可能触发 Rust/MSVC 源码编译，强烈建议改用 Python 3.12。"
            Write-Warn "详见：docs\WINDOWS_DEV_SETUP.md"
        }
    } catch { }
}

if (-not $python) {
    Write-Fail @"
未找到 Python 3.12！

请按以下步骤安装：
  1. 访问 https://www.python.org/downloads/release/python-31210/
  2. 下载 Windows installer（64-bit）
  3. 安装时勾选 "Add Python to PATH"
  4. 重启终端后重新运行本脚本

详细说明：docs\WINDOWS_DEV_SETUP.md
"@
    exit 1
}

# ─── 2. 创建虚拟环境 ──────────────────────────────────────────────────────────
Write-Step "创建虚拟环境 .venv"

if (Test-Path ".venv") {
    Write-Warn ".venv 目录已存在，跳过创建（如需重建请先手动删除 .venv 目录）"
} else {
    Invoke-Expression "$python -m venv .venv"
    Write-Ok ".venv 创建成功"
}

# ─── 3. 激活 venv 并升级 pip ──────────────────────────────────────────────────
Write-Step "激活 .venv 并升级 pip"

$activateScript = Join-Path $repoRoot ".venv\Scripts\Activate.ps1"
if (-not (Test-Path $activateScript)) {
    Write-Fail "找不到 .venv\Scripts\Activate.ps1，venv 创建可能失败，请检查上方报错。"
    exit 1
}

# 在本进程内激活
. $activateScript
Write-Ok "已激活 .venv"

python -m pip install --upgrade pip --quiet
Write-Ok "pip 已升级至 $(python -m pip --version)"

# ─── 4. 安装依赖 ──────────────────────────────────────────────────────────────
Write-Step "安装依赖（app\requirements.txt + requirements-dev.txt）"
Write-Host "  这可能需要 1–3 分钟，请耐心等待..." -ForegroundColor Gray

try {
    pip install -r app\requirements.txt -r requirements-dev.txt
    Write-Ok "依赖安装完成"
} catch {
    Write-Fail @"
依赖安装失败！

常见原因：
  A) Python 版本不是 3.12，asyncpg / pydantic-core 缺少预编译 wheel
     → 换用 Python 3.12 重建 .venv（推荐）
  B) 未安装 Visual Studio Build Tools（C++）+ Rust
     → 安装 VS Build Tools 工作负载"使用 C++ 的桌面开发"
        + https://rustup.rs/

详细故障排除：docs\WINDOWS_DEV_SETUP.md §4
"@
    exit 1
}

# ─── 5. 打印运行提示 ──────────────────────────────────────────────────────────
Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
Write-Host "  环境准备完成！" -ForegroundColor Green
Write-Host ""
Write-Host "  运行测试：" -ForegroundColor White
Write-Host "    pytest -q" -ForegroundColor Yellow
Write-Host ""
Write-Host "  注意：每次新开终端都需要激活 venv：" -ForegroundColor White
Write-Host "    .venv\Scripts\Activate.ps1" -ForegroundColor Yellow
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
Write-Host ""
