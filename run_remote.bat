@echo off
setlocal

:: =============================================
:: MahjongAI Remote - One-click real capture launcher
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
echo   MahjongAI Remote - Real Capture Launcher
echo ============================================
echo.

:: =============================================
:: [1/6] Check Python
:: =============================================
echo [1/6] Checking Python environment...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Python not found. Please install Python 3.8+.
    echo         Download: https://www.python.org/downloads/
    echo         During install, check "Add Python to PATH".
    echo.
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do echo    Python %%v
echo.

:: =============================================
:: [2/6] venv + dependencies
:: =============================================
echo [2/6] Activating venv and installing dependencies...
if exist "venv\Scripts\python.exe" (
    call "venv\Scripts\activate.bat"
    echo    Activated project venv.
) else (
    echo    [NOTE] venv not found, using system Python.
)
pip install requests pyyaml fastapi uvicorn scapy -q
if %errorlevel% neq 0 (
    echo    [NOTE] Dependency install had problems; continuing.
)
echo    Dependency check done.
echo.

:: =============================================
:: [3/6] Bootstrap config
:: =============================================
echo [3/6] Generating and syncing config...
python bootstrap_remote_config.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] bootstrap_remote_config.py failed.
    echo.
    pause
    exit /b 1
)
echo.

:: =============================================
:: [4/6] Mobile hotspot
:: =============================================
echo [4/6] Enabling Mobile Hotspot (router emulation, gateway 192.168.137.1)...
powershell -ExecutionPolicy Bypass -File enable_hotspot.ps1
echo    Waiting for gateway 192.168.137.1 to appear...
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
    echo    Gateway 192.168.137.1 detected, router emulation active.
) else (
    echo    [WARN] Gateway 192.168.137.1 not detected. Extractor may not capture
    echo           any packets. Please turn on Mobile Hotspot manually and connect
    echo           your phone to it. Continuing anyway.
)
echo.

:: =============================================
:: [5/6] Start relay
:: =============================================
echo [5/6] Starting relay in a new window...
start "MahjongAI relay" cmd /k python remote\relay\main.py
echo    Waiting for relay 127.0.0.1:8000 to be ready...
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
if "%RELAY_OK%"=="1" (
    echo    Relay is ready.
) else (
    echo    [WARN] Relay did not become ready in time; check its window. Continuing.
)
echo.

:: =============================================
:: [6/6] Start extractor
:: =============================================
echo [6/6] Starting extractor in a new window...
start "MahjongAI extractor" cmd /k python remote\extractor\main.py
echo.

:: =============================================
:: Foreground: watch live game state
:: =============================================
echo ============================================
echo   Live game state (Ctrl+C to stop watching)
echo ============================================
echo.
python watch_state.py

echo.
echo ============================================
echo   Watcher stopped.
echo   The relay and extractor are still running in their own windows.
echo   Close those windows manually to fully stop the link.
echo ============================================
echo.
pause
endlocal
