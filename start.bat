@echo off
cd /d "%~dp0"

echo ============================================
echo  MahjongAI 一键启动
echo ============================================
echo.

REM ── 检查 Python ──────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] 未检测到 Python，请先安装 Python 3.x
    echo 下载地址: https://www.python.org/downloads/
    echo 安装时请勾选 "Add Python to PATH"
    pause
    exit /b 1
)

echo [1/3] Python 版本:
python --version
echo.

REM ── 检查依赖 ─────────────────────────────────
echo [2/3] 检查依赖...
pip show PyQt6 >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] 检测到依赖缺失，正在安装 requirements.txt ...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo.
        echo [ERROR] 依赖安装失败，请检查网络或手动执行:
        echo   pip install -r requirements.txt
        pause
        exit /b 1
    )
    echo 依赖安装完成。
) else (
    echo 依赖检查通过。
)
echo.

REM ── 启动应用 ─────────────────────────────────
echo [3/3] 启动 MahjongAI ...
echo.
python main.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] 程序异常退出 (exit code %errorlevel%)
    pause
    exit /b %errorlevel%
)

pause
