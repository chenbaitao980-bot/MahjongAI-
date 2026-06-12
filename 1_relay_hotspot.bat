@echo off
setlocal
cd /d "%~dp0"

:: =============================================
::  模式1: 热点模式 — relay :8000
::  手机连PC共享热点 → PC运行extractor抓包 → 推送到此端口
:: =============================================

echo ============================================
echo   MahjongAI Relay - 热点模式 (Hotspot)
echo   Port: 8000
echo   手机连PC共享热点, PC运行extractor抓包推送到此端口
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

:: 启动 relay
echo [启动] 热点模式 relay :8000 ...
echo.
echo 验证: curl http://127.0.0.1:8000/mode
echo 状态: curl "http://127.0.0.1:8000/state?token=acec67bfa9e518b5906d3e6a"
echo.
python remote\relay\main.py --mode hotspot

pause
endlocal
