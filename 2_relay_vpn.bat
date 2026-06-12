@echo off
setlocal
cd /d "%~dp0"

:: =============================================
::  模式2: VPN模式 — relay :8001
::  手机配置IPSec VPN连云端 → 云端ECS抓包 → 推送到此端口
::  注意: VPN模式通常在云端ECS上运行, 此bat仅用于本地调试
:: =============================================

echo ============================================
echo   MahjongAI Relay - VPN模式 (Phone VPN)
echo   Port: 8001
echo   手机配置IPSec VPN连云端, ECS抓包推送到此端口
echo   [注意] VPN模式通常在云端ECS上运行
:: =============================================
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
echo [启动] VPN模式 relay :8001 ...
echo.
echo 验证: curl http://127.0.0.1:8001/mode
echo 状态: curl "http://127.0.0.1:8001/state?token=8f2e7c91b4d53a6f10e9c827"
echo.
python remote\relay\main.py --mode vpn

pause
endlocal
