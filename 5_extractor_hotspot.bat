@echo off
setlocal
chcp 65001 >nul 2>&1

:: =============================================
::  Hotspot Mode Extractor (Npcap) - needs admin
::  Phone -> PC hotspot -> Npcap capture -> relay :8000
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
echo   MahjongAI Extractor - Hotspot Mode (Npcap)
echo   Capture port: 7777
echo ============================================
echo.

:: Activate venv
if exist ".venv\Scripts\python.exe" (
    call ".venv\Scripts\activate.bat"
) else if exist "venv\Scripts\python.exe" (
    call "venv\Scripts\activate.bat"
)

:: Install deps
pip install scapy pyyaml requests cryptography -q 2>nul

echo [Tips] Make sure:
echo   1. Phone connected to PC hotspot (192.168.137.x)
echo   2. Relay running on :8000 (run 1_relay_hotspot.bat)
echo   3. Clear game app data then re-login (first time for credentials)
echo.

:: Open remote ECS web page
echo [Web] Opening remote ECS page http://8.136.37.136:8000/ ...
start "" http://8.136.37.136:8000/
echo.

:: Start extractor
echo [Start] Hotspot extractor (Npcap) ...
echo.
python remote\extractor\main.py --mode npcap

pause
endlocal
