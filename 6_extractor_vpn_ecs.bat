@echo off
setlocal
chcp 65001 >nul 2>&1

:: =============================================
::  VPN Mode Extractor - Push to ECS
::  Usually runs ON the ECS, this bat is for local debug
:: =============================================

:: UAC self-elevation
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting admin privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

echo ============================================
echo   MahjongAI - VPN Mode ECS Extractor
echo   Cloud relay: http://8.136.37.136:8001
echo ============================================
echo.

:: Activate venv
if exist ".venv\Scripts\python.exe" (
    call ".venv\Scripts\python.exe" -m pip install cryptography -q 2>nul
) else (
    python -m pip install cryptography -q 2>nul
)

echo [NOTE] VPN extractor normally runs on ECS.
echo   For ECS deployment, SSH and run:
echo     ssh root@8.136.37.136
echo     cd /opt/mahjong-remote
echo     python3 remote/extractor/main.py --mode tcpdump --interface ipsec0
echo.

echo [Start] Local extractor pushing to ECS VPN relay :8001 ...
echo.
python remote\extractor\main.py --mode npcap --config remote\extractor\config_vpn_ecs.yaml

pause
endlocal
