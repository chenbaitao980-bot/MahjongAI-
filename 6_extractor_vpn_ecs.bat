@echo off
setlocal

:: =============================================
::  VPN模式 Extractor (推送到云端ECS)
::  手机连VPN → 云端ECS抓包 → 推送到relay :8001
::  此bat用于从本地PC推送extractor到ECS并远程启动
:: =============================================

:: --- UAC self-elevation ---
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo 需要管理员权限, 正在请求提权...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

echo ============================================
echo   MahjongAI - VPN模式 ECS Extractor
::   云端relay: http://8.136.37.136:8001
echo ============================================
echo.

:: 激活 venv
if exist ".venv\Scripts\python.exe" (
    call ".venv\Scripts\python.exe" -m pip install cryptography -q 2>nul
) else (
    python -m pip install cryptography -q 2>nul
)

echo [提示] VPN模式的extractor运行在云端ECS上.
echo   本bat用于本地调试, 从本地PC直接抓包推送到云端.
echo.
echo   如果extractor应部署在ECS上, 请SSH到ECS运行:
echo     ssh root@8.136.37.136
echo     cd /opt/mahjong-remote
echo     python3 remote/extractor/main.py --mode tcpdump --interface ipsec0 --config remote/extractor/config_vpn_ecs.yaml
echo.

:: 启动本地extractor (推送到云端)
echo [启动] 本地extractor 推送到云端VPN relay :8001 ...
echo.
python remote\extractor\main.py --mode npcap --config remote\extractor\config_vpn_ecs.yaml

pause
endlocal
