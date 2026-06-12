@echo off
setlocal

:: =============================================
::  热点模式 Extractor (Npcap) — 需管理员权限
::  手机连PC共享热点 → Npcap抓包 → 推送到relay :8000
:: =============================================

:: --- UAC self-elevation (Npcap needs admin) ---
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo 需要管理员权限运行 (Npcap抓包需要), 正在请求提权...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

echo ============================================
echo   MahjongAI Extractor - 热点模式 (Npcap)
echo   抓包端口: 7777
::   推送目标: 见 remote/extractor/config.yaml
echo ============================================
echo.

:: 激活 venv
if exist ".venv\Scripts\python.exe" (
    call ".venv\Scripts\activate.bat"
) else if exist "venv\Scripts\python.exe" (
    call "venv\Scripts\activate.bat"
)

:: 安装依赖
pip install scapy pyyaml requests cryptography -q 2>nul

echo [提示] 请确保:
echo   1. 手机已连上PC共享热点 (192.168.137.x)
echo   2. relay已在 :8000 运行 (双击 1_relay_hotspot.bat)
echo   3. 游戏App已清除数据并重新登录 (首次提取凭证)
echo.

:: 启动 extractor
echo [启动] 热点模式 extractor (Npcap) ...
echo.
python remote\extractor\main.py --mode npcap

pause
endlocal
