@echo off
setlocal
chcp 65001 >nul 2>&1

:: =============================================
::  All-Mode Relay - Ports 8000/8001/8002
:: =============================================

echo ============================================
echo   MahjongAI Relay - All Modes
echo   :8000 Hotspot | :8001 VPN | :8002 No-Config
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

echo [Start] All three modes ...
echo.
echo   Hotspot:  http://127.0.0.1:8000/mode
echo   VPN:      http://127.0.0.1:8001/mode
echo   No-Config: http://127.0.0.1:8002/mode
echo.
python remote\relay\main.py --all

pause
endlocal
