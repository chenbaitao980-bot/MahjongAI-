@echo off
setlocal
chcp 65001 >nul 2>&1

:: =============================================
::  Hotspot One-Click - relay + extractor
::  Phone -> PC hotspot -> capture -> relay :8000
:: =============================================

:: UAC self-elevation (Npcap needs admin)
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting admin privileges for Npcap capture...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

echo ============================================
echo   MahjongAI Hotspot One-Click
echo   relay :8000 + extractor (Npcap)
echo ============================================
echo.

:: Activate venv
if exist ".venv\Scripts\python.exe" (
    call ".venv\Scripts\activate.bat"
) else if exist "venv\Scripts\python.exe" (
    call "venv\Scripts\activate.bat"
)

:: Install deps
pip install fastapi uvicorn pyyaml requests cryptography scapy -q 2>nul

:: [1/2] Start relay
echo [1/2] Starting hotspot relay :8000 ...
start "Relay-Hotspot" cmd /k python remote\relay\main.py --mode hotspot
echo    Waiting for relay ...

set RELAY_OK=0
for /l %%i in (1,1,20) do (
    python -c "import requests; r=requests.get('http://127.0.0.1:8000/mode',timeout=2); exit(0 if r.status_code==200 else 1)" >nul 2>&1
    if not errorlevel 1 (
        set RELAY_OK=1
        goto :relay_done
    )
    powershell -Command "Start-Sleep -Milliseconds 1000" >nul
)
:relay_done
if "%RELAY_OK%"=="1" (
    echo    [OK] Relay ready
) else (
    echo    [WARN] Relay not ready, check Relay-Hotspot window
)
echo.

:: [2/2] Start extractor
echo [2/2] Starting hotspot extractor (Npcap) ...
echo.
echo =============================================
echo   Connect phone to PC hotspot, open game,
echo   clear app data then re-login.
echo   Data will appear at: http://127.0.0.1:8000/
echo =============================================
echo.
start "Extractor-Hotspot" cmd /k python remote\extractor\main.py --mode npcap

:: Open browser
start http://127.0.0.1:8000/

echo.
echo   Relay and extractor started in separate windows.
echo   Close those windows to stop.
echo.
pause
endlocal
