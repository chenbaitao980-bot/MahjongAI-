@echo off
setlocal
chcp 65001 >nul 2>&1

:: =============================================
::  No-Config Mode Relay - Port 8002
::  SRS spectator connects directly to game server
::  Phone needs NO configuration at all
:: =============================================

echo ============================================
echo   MahjongAI Relay - No-Config Mode
echo   Port: 8002  |  Spectator: :8003
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

echo [Start] No-Config relay :8002 ...
echo.
echo Verify: curl http://127.0.0.1:8002/mode
echo State:  curl "http://127.0.0.1:8002/state?token=d4a8e1f29c6b7305e8d1f264"
echo.
python remote\relay\main.py --mode noconfig

pause
endlocal
