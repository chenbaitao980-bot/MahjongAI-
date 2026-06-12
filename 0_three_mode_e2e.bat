@echo off
setlocal

:: =============================================
::  三模式 E2E 测试 — 一键启动 + 验证
::  1. 启动三模式 relay (:8000/:8001/:8002)
::  2. 启动热点模式 extractor (Npcap)
::  3. 运行 E2E 验证脚本
:: =============================================

:: --- UAC self-elevation (extractor needs admin) ---
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo 需要管理员权限运行 (Npcap抓包需要), 正在请求提权...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

echo ============================================
echo   MahjongAI 三模式 E2E 测试
echo   热点(:8000) + VPN(:8001) + 无配置(:8002)
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
:: [1/4] 启动三模式 relay
:: =============================================
echo [1/4] 启动三模式 relay ...
start "Relay-All" cmd /k python remote\relay\main.py --all
echo    等待 relay 就绪...

set RELAY_OK=0
for /l %%i in (1,1,30) do (
    python -c "import requests; r=requests.get('http://127.0.0.1:8000/mode',timeout=2); exit(0 if r.status_code==200 else 1)" >nul 2>&1
    if not errorlevel 1 (
        set RELAY_OK=1
        goto :relay_ready
    )
    powershell -Command "Start-Sleep -Milliseconds 1000" >nul
)
:relay_ready
if "%RELAY_OK%"=="1" (
    echo    [OK] 三模式 relay 已就绪
) else (
    echo    [WARN] relay 未就绪, 请检查 Relay-All 窗口
)
echo.

:: =============================================
:: [2/4] 启动热点模式 extractor
:: =============================================
echo [2/4] 启动热点模式 extractor ...
echo    [提示] 请确保手机已连PC共享热点
start "Extractor-Hotspot" cmd /k python remote\extractor\main.py --mode npcap
echo    extractor 已在新窗口启动
echo.

:: =============================================
:: [3/4] 运行 E2E 验证
:: =============================================
echo [3/4] 运行 E2E 验证脚本 ...
echo --------------------------------------------
python e2e_test.py
set E2E_RC=%errorlevel%
echo --------------------------------------------
echo.

:: =============================================
:: [4/4] 打开浏览器查看
:: =============================================
echo [4/4] 打开浏览器查看各模式状态...
start http://127.0.0.1:8000/
echo.

:: =============================================
:: 汇总
:: =============================================
echo ============================================
echo   三模式 E2E 测试结果
echo ============================================
if "%E2E_RC%"=="0" (
    echo   E2E 验证: PASS
) else (
    echo   E2E 验证: FAIL ^(rc=%E2E_RC%^)
)
echo.
echo   热点模式:  http://127.0.0.1:8000/
echo   VPN模式:   http://127.0.0.1:8001/
echo   无配置模式: http://127.0.0.1:8002/
echo.
echo   relay和extractor仍在独立窗口运行.
echo   关闭那些窗口即可停止.
echo ============================================
echo.

pause
endlocal
