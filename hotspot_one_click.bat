@echo off
setlocal
cd /d "%~dp0"

:: =============================================
::  热点模式一键启动 — relay + extractor 联动
::  手机连PC共享热点 → PC抓包 → relay :8000
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
echo   MahjongAI 热点模式一键启动
::   relay :8000 + extractor (Npcap)
echo ============================================
echo.

:: 激活 venv
if exist ".venv\Scripts\python.exe" (
    call ".venv\Scripts\activate.bat"
) else if exist "venv\Scripts\python.exe" (
    call "venv\Scripts\activate.bat"
)

:: 安装依赖
pip install fastapi uvicorn pyyaml requests cryptography scapy -q 2>nul

:: =============================================
:: [1/2] 启动 relay
:: =============================================
echo [1/2] 启动热点模式 relay :8000 ...
start "Relay-Hotspot" cmd /k python remote\relay\main.py --mode hotspot
echo    等待 relay 就绪...

set RELAY_OK=0
for /l %%i in (1,1,20) do (
    python -c "import requests; r=requests.get('http://127.0.0.1:8000/mode',timeout=2); exit(0 if r.status_code==200 else 1)" >nul 2>&1
    if not errorlevel 1 (
        set RELAY_OK=1
        goto :relay_done
    )
    powershell -Command "Start-Sleep -Milliseconds 1000" >nul
)
:relay_done
if "%RELAY_OK%"=="1" (
    echo    [OK] relay 已就绪
) else (
    echo    [WARN] relay 未就绪, 请检查 Relay-Hotspot 窗口
)
echo.

:: =============================================
:: [2/2] 启动 extractor
:: =============================================
echo [2/2] 启动热点模式 extractor (Npcap) ...
echo.
echo =============================================
echo   手机连PC共享热点, 打开游戏, 清除App数据后重新登录
echo   数据将显示在: http://127.0.0.1:8000/
echo =============================================
echo.
start "Extractor-Hotspot" cmd /k python remote\extractor\main.py --mode npcap

:: 打开浏览器
start http://127.0.0.1:8000/

echo.
echo   relay和extractor已在新窗口启动.
echo   关闭那些窗口即可停止.
echo.
pause
endlocal
