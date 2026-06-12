@echo off
setlocal
chcp 65001 >nul 2>&1

:: =============================================
::  VPN Mode Relay - Port 8001
::  Phone IPSec VPN -> ECS capture -> relay
::  NOTE: VPN mode usually runs on ECS, this is for local debug
:: =============================================

echo ============================================
echo   MahjongAI Relay - VPN Mode
echo   Port: 8001
echo   [NOTE] VPN mode usually runs on ECS
echo ============================================
echo.

:: Activate venv
if exist ".venv\Scripts\python.exe" (
    call ".venv\Scripts\activate.bat"
) else if exist "venv\Scripts\python.exe" (
    call "venv\Scripts\activate.bat"
)

:: Install deps
pip install fastapi uvicorn pyyaml requests cryptography -q 2>nul

echo [Start] VPN relay :8001 ...
echo.
echo Verify: curl http://127.0.0.1:8001/mode
echo State:  curl "http://127.0.0.1:8001/state?token=8f2e7c91b4d53a6f10e9c827"
echo.
python remote\vpn\main.py

pause
endlocal
