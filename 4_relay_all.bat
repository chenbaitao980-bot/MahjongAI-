@echo off
setlocal
cd /d "%~dp0"

:: =============================================
::  三模式同时启动 — relay :8000/:8001/:8002
::  各模式独立端口, 互不影响
:: =============================================

echo ============================================
echo   MahjongAI Relay - 三模式同时启动
echo   :8000 热点 | :8001 VPN | :8002 无配置
echo ============================================
echo.

:: 激活 venv
if exist ".venv\Scripts\python.exe" (
    call ".venv\Scripts\activate.bat"
) else if exist "venv\Scripts\python.exe" (
    call "venv\Scripts\activate.bat"
)

:: 安装依赖
pip install fastapi uvicorn pyyaml requests cryptography -q 2>nul

:: 启动全部模式
echo [启动] 三模式全部启动...
echo.
echo   热点模式:  http://127.0.0.1:8000/mode
echo   VPN模式:   http://127.0.0.1:8001/mode
echo   无配置模式: http://127.0.0.1:8002/mode
echo.
python remote\relay\main.py --all

pause
endlocal
