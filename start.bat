@echo off
cd /d "%~dp0"

echo ============================================
echo   MahjongAI 一键启动
echo ============================================
echo.

:: =============================================
:: Step 1: Check Python
:: =============================================
echo [1/4] 检查 Python 环境...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [错误] 未找到 Python，请先安装 Python 3.x
    echo         下载地址: https://www.python.org/downloads/
    echo         安装时请勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do echo    Python %%v
echo.

:: =============================================
:: Step 2: Check / Create venv
:: =============================================
echo [2/4] 检查虚拟环境...
if not exist "venv\Scripts\python.exe" (
    echo    未找到虚拟环境，正在创建...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo.
        echo [错误] 创建虚拟环境失败，请检查 Python 安装
        echo.
        pause
        exit /b 1
    )
    echo    虚拟环境创建完成
) else (
    echo    虚拟环境已存在
)

call "venv\Scripts\activate.bat"
if %errorlevel% neq 0 (
    echo.
    echo [错误] 激活虚拟环境失败
    echo.
    pause
    exit /b 1
)
echo.

:: =============================================
:: Step 3: Install dependencies
:: =============================================
echo [3/4] 检查并安装依赖...
pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo.
    echo [错误] 依赖安装失败，请检查网络连接后重试
    echo         或手动运行: pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)
echo    依赖就绪
echo.

:: =============================================
:: Step 4: Launch main.py
:: =============================================
echo [4/4] 启动 MahjongAI...
echo.
echo ============================================
echo   应用已启动，请勿关闭此窗口
echo   关闭此窗口将同时退出应用
echo ============================================
echo.

python main.py

if %errorlevel% neq 0 (
    echo.
    echo [提示] 应用已退出 (错误码: %errorlevel%)
    echo.
    pause
    exit /b %errorlevel%
)

echo.
echo 应用已正常退出
echo.
pause
