# Windows 本机开发环境配置指南

> 适用对象：在 Windows 上首次搭建 ERIS 开发环境的工程师  
> 对应 Docker 镜像：`app/Dockerfile`（Python **3.12**-slim）  
> 任务卡：D8-DEV-03

---

## 目录

1. [推荐环境（快速上手）](#1-推荐环境快速上手)
2. [逐步操作说明](#2-逐步操作说明)
3. [运行测试](#3-运行测试)
4. [故障排除](#4-故障排除)
5. [Python 版本对比](#5-python-版本对比)
6. [可选：WSL2 路径](#6-可选wsl2-路径)

---

## 1. 推荐环境（快速上手）

| 组件 | 推荐版本 | 说明 |
|------|---------|------|
| Python | **3.12.x** | 与 `app/Dockerfile` 保持一致；所有依赖均有预编译 wheel |
| pip | ≥ 24.0 | `python -m pip install --upgrade pip` |
| Git | 任意 | 已有则跳过 |
| VS Build Tools | **不需要**（走 3.12 路径） | 仅在强制使用 3.14 时才需要 |

> **强烈不建议** 使用 Python 3.14 安装生产依赖：`asyncpg` 和 `pydantic-core`
> 在 3.14 上尚无预编译 wheel，pip 会尝试 Rust（maturin）+ MSVC 源码编译，
> 若本机未装 Visual Studio Build Tools 会直接报错中断。详见 [§5](#5-python-版本对比)。

---

## 2. 逐步操作说明

### 2.1 安装 Python 3.12

从官网下载安装包：<https://www.python.org/downloads/release/python-31210/>

安装时勾选 **"Add Python to PATH"**（或 **"Add python.exe to PATH"**）。

安装完成后验证：

```powershell
py -3.12 --version
# 应输出 Python 3.12.x
```

> 如果 `py` 找不到 3.12，可以用 `python --version` 确认默认版本，
> 或用 `python3.12 --version`（需要将安装目录加入 PATH）。

### 2.2 克隆仓库（已有则跳过）

```powershell
git clone https://github.com/hailuo313-tech/hugme.git
cd hugme
```

### 2.3 创建虚拟环境

在**仓库根目录**执行：

```powershell
py -3.12 -m venv .venv
```

激活虚拟环境：

```powershell
.venv\Scripts\Activate.ps1
```

> 若报 "execution of scripts is disabled"，以管理员身份运行：
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

激活后命令提示符前缀会变为 `(.venv)`。

### 2.4 升级 pip

```powershell
python -m pip install --upgrade pip
```

### 2.5 安装依赖

```powershell
pip install -r app\requirements.txt -r requirements-dev.txt
```

预期输出：全部 `Successfully installed`，无 `Building wheel` / `error: command failed` 字样。

> **说明**：`requirements-dev.txt` 包含 `pytest`、`pytest-asyncio` 以及
> `tzdata`（Windows 上 `zoneinfo` 需要它提供 IANA 时区数据库，
> Linux 容器自带系统时区数据所以不需要）。

---

## 3. 运行测试

在**仓库根目录**（不是 `app/` 下）执行：

```powershell
pytest -q
```

`pytest.ini` 已配置 `pythonpath = app`，测试可正确解析 `from core...` / `from services...` 等导入。

完整带详情输出：

```powershell
pytest -v
```

---

## 4. 故障排除

### 4.1 `pip install` 失败：无法编译 `asyncpg` / `pydantic-core`

**症状**：

```
error: Microsoft Visual C++ 14.0 or greater is required.
```

或：

```
error[E0463]: can't find crate for `std`
```

**原因**：当前 Python 版本（通常是 3.13 / 3.14）缺少预编译 wheel，pip 尝试源码编译。

**解决方案（二选一）**：

**方案 A（推荐）：换用 Python 3.12**

参考 [§2.1](#21-安装-python-312) 安装 3.12，再用 `py -3.12 -m venv .venv` 重建 venv。

**方案 B：安装 Visual Studio Build Tools + Rust**

1. 下载 [VS Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
2. 勾选工作负载：**"使用 C++ 的桌面开发"**（Desktop development with C++）
3. 安装 Rust：<https://rustup.rs/>，执行 `rustup default stable`
4. 重启终端，重新 `pip install`

> 方案 B 安装包约 5 GB，耗时 15–30 分钟。建议优先走方案 A。

### 4.2 `ModuleNotFoundError: No module named 'fastapi'`

**原因**：依赖安装不完整，或在未激活 venv 的环境里运行 pytest。

**解决**：

```powershell
# 确认已激活 .venv
.venv\Scripts\Activate.ps1
# 重新安装
pip install -r app\requirements.txt -r requirements-dev.txt
```

### 4.3 `pytest` 报 `zoneinfo.ZoneInfoNotFoundError`

**原因**：Windows 缺少系统时区数据库，需要 `tzdata` 包。

**解决**：

```powershell
pip install "tzdata>=2024.1"
```

（正常情况下 `requirements-dev.txt` 已包含此依赖，重新 `pip install` 即可。）

### 4.4 `pytest` 命令找不到

```powershell
# 确认 .venv 已激活，再验证
pytest --version
# 或用完整路径
.venv\Scripts\pytest.exe --version
```

### 4.5 PowerShell 脚本执行权限

```powershell
# 以管理员身份运行 PowerShell，执行：
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

---

## 5. Python 版本对比

| Python 版本 | asyncpg wheel | pydantic-core wheel | 推荐程度 | 说明 |
|-------------|:---:|:---:|:---:|------|
| **3.12.x** | ✅ | ✅ | ⭐ **推荐** | 与 Dockerfile 对齐，无需编译工具 |
| 3.11.x | ✅ | ✅ | ✅ 可用 | 可用但与生产略有差异 |
| 3.13.x | ⚠️ | ⚠️ | 谨慎 | 部分版本有 wheel，但可能滞后发布 |
| 3.14.x | ❌ | ❌ | 🚫 **不推荐** | 目前无预编译 wheel，强制编译需 MSVC + Rust |

---

## 6. 可选：WSL2 路径

如果你经常需要与 Linux 容器行为保持一致，或者在 Windows 上遇到难以解决的编译问题，
推荐使用 WSL2（Ubuntu 22.04 / 24.04）：

```bash
# WSL2 Ubuntu 内
sudo apt update && sudo apt install python3.12 python3.12-venv python3.12-dev -y
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r app/requirements.txt -r requirements-dev.txt
pytest -q
```

WSL2 内运行 `pytest` 的结果与 CI / Docker 最为接近。

---

## 快速参考

```powershell
# 一次完整的从零到 pytest 通过（Python 3.12 已安装）
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r app\requirements.txt -r requirements-dev.txt
pytest -q
```

也可以运行一键脚本（需先安装 Python 3.12）：

```powershell
.\scripts\bootstrap_windows_dev.ps1
```

---

*最后更新：2026-05-14 | 维护：D8-DEV-03*
