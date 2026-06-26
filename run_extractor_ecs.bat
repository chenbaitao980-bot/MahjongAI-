@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   MahjongAI - ECS Extractor Launcher
echo   relay: http://8.136.37.136:8000
echo ============================================
echo.

:: --- UAC self-elevation ---
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting admin privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

:: --- Install deps ---
echo Installing dependencies...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m pip install cryptography -q 2>nul
) else (
    python -m pip install cryptography -q 2>nul
)
echo Done.
echo.

:: --- Bootstrap config ---
echo Syncing config with ECS...
python bootstrap_remote_config.py
if %errorlevel% neq 0 (
    echo Config sync failed!
    pause
    exit /b 1
)
echo.

:: --- Open ECS web page ---
start http://8.136.37.136:8000/

:: --- Start extractor ---
echo Starting extractor (pushing to ECS)...
echo.
echo =============================================
echo   Connect phone to hotspot NOW.
echo   Open the game and log in.
echo   Data will appear at http://8.136.37.136:8000/
echo =============================================
echo.

python remote\extractor\main.py

pause
endlocal
