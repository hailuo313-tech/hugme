@echo off
echo ========================================
echo ERIS 服务启动脚本 (Windows)
echo ========================================
echo.

cd /d E:\eris

echo [1/3] 检查Python环境...
python --version
if errorlevel 1 (
    echo 错误: Python未安装或不在PATH中
    echo 请安装Python: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo.
echo [2/3] 安装Python依赖...
pip install -r requirements.txt
if errorlevel 1 (
    echo 错误: 依赖安装失败
    pause
    exit /b 1
)

echo.
echo [3/3] 启动后端服务...
echo 注意: 此方式需要PostgreSQL服务单独启动
echo 如果没有PostgreSQL，请使用Docker方式启动
echo.

cd app
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

pause