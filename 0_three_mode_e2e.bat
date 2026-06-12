@echo off
setlocal
chcp 65001 >nul 2>&1

:: =============================================
::  Three-Mode E2E Test - Launch + Verify
:: =============================================

:: UAC self-elevation (extractor needs admin)
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting admin privileges for Npcap capture...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

echo ============================================
echo   MahjongAI Three-Mode E2E Test
echo   Hotspot(:8000) + VPN(:8001) + No-Config(:8002)
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

:: [1/4] Start three-mode relay
echo [1/4] Starting three-mode relay ...
start "Relay-All" cmd /k python remote\relay\main.py --all
echo    Waiting for relay ...

set RELAY_OK=0
for /l %%i in (1,1,30) do (
    python -c "import requests; r=requests.get('http://127.0.0.1:8000/mode',timeout=2); exit(0 if r.status_code==200 else 1)" >nul 2>&1
    if not errorlevel 1 (
        set RELAY_OK=1
        goto :relay_ready
    )
    powershell -Command "Start-Sleep -Milliseconds 1000" >nul
)
:relay_ready
if "%RELAY_OK%"=="1" (
    echo    [OK] Three-mode relay ready
) else (
    echo    [WARN] Relay not ready, check Relay-All window
)
echo.

:: [2/4] Start hotspot extractor
echo [2/4] Starting hotspot extractor ...
echo    [Tip] Make sure phone connected to PC hotspot
start "Extractor-Hotspot" cmd /k python remote\extractor\main.py --mode npcap
echo    Extractor started in new window
echo.

:: [3/4] Run E2E verify
echo [3/4] Running E2E verification ...
echo --------------------------------------------
python e2e_test.py
set E2E_RC=%errorlevel%
echo --------------------------------------------
echo.

:: [4/4] Open browser
echo [4/4] Opening browser ...
start http://127.0.0.1:8000/
echo.

:: Summary
echo ============================================
echo   Three-Mode E2E Test Result
echo ============================================
if "%E2E_RC%"=="0" (
    echo   E2E Verify: PASS
) else (
    echo   E2E Verify: FAIL ^(rc=%E2E_RC%^)
)
echo.
echo   Hotspot:   http://127.0.0.1:8000/
echo   VPN:       http://127.0.0.1:8001/
echo   No-Config: http://127.0.0.1:8002/
echo.
echo   Relay and extractor still running in separate windows.
echo   Close those windows to stop.
echo ============================================
echo.

pause
endlocal
