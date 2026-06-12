@echo off
setlocal
chcp 65001 >nul 2>&1

:: =============================================
::  Hotspot Mode Relay - Port 8000
::  Phone -> PC hotspot -> extractor -> relay
:: =============================================

echo ============================================
echo   MahjongAI Relay - Hotspot Mode
echo   Port: 8000
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

echo [Start] Hotspot relay :8000 ...
echo.
echo Verify: curl http://127.0.0.1:8000/mode
echo State:  curl "http://127.0.0.1:8000/state?token=acec67bfa9e518b5906d3e6a"
echo.
python remote\relay\main.py --mode hotspot

pause
endlocal
