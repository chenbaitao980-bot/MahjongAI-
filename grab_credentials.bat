@echo off
setlocal

REM grab_credentials.bat
REM Capture srs_sessionid from hotspot traffic and auto-upload to ECS.
REM Requires: Npcap installed, phone connected to PC hotspot, game open in a room.

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

REM Run capture (Phase 1: grab credentials; Phase 2: watch for game entry)
REM Browser opens automatically when credentials are ready.
REM Press Ctrl+C to stop.
python remote\capture_credentials.py --ecs-relay http://8.136.37.136:8003 %*

pause
