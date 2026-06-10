@echo off
setlocal

:: =============================================
:: MahjongAI - Local capture test + hand UI
:: Starts relay + extractor locally and opens the
:: live hand page in your browser to verify capture.
:: =============================================

:: --- UAC self-elevation (extractor packet capture needs admin) ---
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

echo ============================================
echo   MahjongAI - Capture Test + Hand UI
echo ============================================
echo.

:: [1/7] Python
echo [1/7] Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install Python 3.8+ and check "Add to PATH".
    pause
    exit /b 1
)

:: [2/7] venv + deps
echo [2/7] venv and dependencies...
if exist "venv\Scripts\python.exe" (
    call "venv\Scripts\activate.bat"
    echo    Activated project venv.
) else (
    echo    [NOTE] venv not found, using system Python.
)
pip install requests pyyaml fastapi uvicorn scapy -q
if %errorlevel% neq 0 echo    [NOTE] Dependency install had problems; continuing.

:: [3/7] Bootstrap config (generates/syncs api_token)
echo [3/7] Config...
python bootstrap_remote_config.py
if %errorlevel% neq 0 (
    echo [ERROR] bootstrap_remote_config.py failed.
    pause
    exit /b 1
)

:: read api_token from config for the browser URL
set API_TOKEN=
for /f "delims=" %%t in ('python -c "import yaml;print(yaml.safe_load(open('remote/relay/config.yaml'))['api_token'])"') do set API_TOKEN=%%t
echo    api_token = %API_TOKEN%

:: [4/7] Mobile hotspot
echo [4/7] Enabling Mobile Hotspot (gateway 192.168.137.1)...
powershell -ExecutionPolicy Bypass -File enable_hotspot.ps1
echo    Waiting for gateway 192.168.137.1...
set HOTSPOT_OK=0
for /l %%i in (1,1,30) do (
    ipconfig | findstr 192.168.137.1 >nul
    if not errorlevel 1 (
        set HOTSPOT_OK=1
        goto :hotspot_done
    )
    powershell -Command "Start-Sleep -Milliseconds 1000" >nul
)
:hotspot_done
if "%HOTSPOT_OK%"=="1" (
    echo    Gateway detected, router emulation active.
) else (
    echo    [WARN] 192.168.137.1 not found. Turn on Mobile Hotspot and connect your phone.
)

:: [5/7] Start relay
echo [5/7] Starting relay...
start "MahjongAI relay" cmd /k python remote\relay\main.py
echo    Waiting for relay 127.0.0.1:8000...
set RELAY_OK=0
for /l %%i in (1,1,20) do (
    python -c "import requests,sys; sys.exit(0 if requests.get('http://127.0.0.1:8000/state',params={'token':'x'},timeout=2).status_code in (200,401) else 1)" >nul 2>&1
    if not errorlevel 1 (
        set RELAY_OK=1
        goto :relay_done
    )
    powershell -Command "Start-Sleep -Milliseconds 1000" >nul
)
:relay_done
if "%RELAY_OK%"=="1" (echo    Relay ready.) else (echo    [WARN] Relay not ready; check its window.)

:: [6/7] Start extractor
echo [6/7] Starting extractor...
start "MahjongAI extractor" cmd /k python remote\extractor\main.py

:: [7/7] Open hand UI in browser
echo [7/7] Opening hand UI in browser...
start "" "http://127.0.0.1:8000/?token=%API_TOKEN%"

echo.
echo ============================================
echo   Done. Now on your PHONE:
echo     1) connect to this PC's Mobile Hotspot
echo     2) enter a NEW game round
echo   Your hand tiles will appear in the browser page.
echo ----------------------------------------------
echo   Hand UI : http://127.0.0.1:8000/?token=%API_TOKEN%
echo   relay and extractor run in their own windows.
echo   Close those windows to stop.
echo ============================================
echo.
pause
endlocal
