@echo off
setlocal
cd /d "%~dp0"

:: =============================================
::  模式3: 无配置模式 — relay :8002
::  SRS spectator直连游戏服务器, 手机无需任何配置
::  需要先通过extractor获取SRS凭证
:: =============================================

echo ============================================
echo   MahjongAI Relay - 无配置模式 (No-Config)
echo   Port: 8002  |  Spectator: :8003
echo   SRS旁观协议直连游戏服务器, 手机无需任何配置
echo ============================================
echo.

:: 激活 venv
if exist ".venv\Scripts\python.exe" (
    call ".venv\Scripts\activate.bat"
) else if exist "venv\Scripts\python.exe" (
    call "venv\Scripts\activate.bat"
)

:: 安装依赖
pip install fastapi uvicorn pyyaml requests cryptography -q 2>nul

:: 启动 relay
echo [启动] 无配置模式 relay :8002 ...
echo.
echo 验证: curl http://127.0.0.1:8002/mode
echo 状态: curl "http://127.0.0.1:8002/state?token=d4a8e1f29c6b7305e8d1f264"
echo 旁观: curl http://127.0.0.1:8003/status
echo.
python remote\relay\main.py --mode noconfig

pause
endlocal
