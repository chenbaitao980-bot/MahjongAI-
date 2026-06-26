@echo off
setlocal

REM start_cloud_player.bat
REM Full local pipeline: read credentials -> start relay -> open browser -> connect as player
REM Prerequisites: run grab_credentials.bat first to capture srs_sessionid

REM UAC elevation
net session >nul 2>&1
if %errorlevel% NEQ 0 (
    echo [UAC] Requesting administrator privileges...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b 0
)

REM Change to project root
cd /d "%~dp0"

REM Activate venv if available
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

REM Check credentials file
if not exist "data\cloud_credentials.json" (
    echo [ERROR] data\cloud_credentials.json not found.
    echo         Please run grab_credentials.bat first to capture credentials.
    pause
    exit /b 1
)

REM Read sessionid from JSON via PowerShell
for /f "usebackq delims=" %%i in (
    `powershell -NoProfile -Command "(Get-Content 'data\cloud_credentials.json' | ConvertFrom-Json).srs_sessionid"`
) do set SRS_SESSIONID=%%i

if "%SRS_SESSIONID%"=="" (
    echo [ERROR] srs_sessionid is empty in data\cloud_credentials.json.
    echo         Please run grab_credentials.bat again to capture fresh credentials.
    pause
    exit /b 1
)

echo [OK] srs_sessionid loaded: %SRS_SESSIONID:~0,8%...

REM Start relay server in background
echo [Starting] Cloud relay on port 8003...
start "MahjongAI Cloud Relay" /min python remote\relay\main.py --mode cloud --port 8003

REM Wait for relay to be ready
timeout /t 2 /nobreak >nul

REM Open browser
echo [Opening] Browser at http://localhost:8003
start "" "http://localhost:8003"

REM Start cloud player
echo [Connecting] Cloud player connecting to game server...
echo              Hand tiles will appear in browser when you are in a game.
echo              Press Ctrl+C to stop.
echo.
python remote\cloud_player.py --creds data\cloud_credentials.json --relay http://localhost:8003 --api-token cloudmode2026

pause
