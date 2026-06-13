"""全局测试配置。

项目运行时 ``PYTHONPATH=/app``（Docker 镜像 WORKDIR=/app），所以业务代码用
``from core.config ...`` / ``from services.llm ...`` 这种「顶层 app/」风格 import。
pytest 通过 ``pytest.ini`` 的 ``pythonpath = app`` 已经对齐了这一约定；
本文件兜底确保即便用 IDE / 工具绕过 pytest.ini 启动测试时 sys.path 也含 ``app/``。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "app"

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
