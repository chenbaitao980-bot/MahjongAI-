@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   MahjongAI Remote 服务测试 + 诊断
echo ============================================
echo.

:: =============================================
:: Step 1: Check Python
:: =============================================
echo [1/5] 检查 Python 环境...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    echo         下载地址: https://www.python.org/downloads/
    echo         安装时请勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do echo    Python %%v
echo.

:: =============================================
:: Step 2: Activate venv (if present)
:: =============================================
echo [2/5] 检查虚拟环境...
if exist "venv\Scripts\python.exe" (
    call "venv\Scripts\activate.bat"
    echo    已激活项目虚拟环境 venv
) else (
    echo    [提示] 未找到 venv，使用系统 Python
)
echo.

:: =============================================
:: Step 3: Ensure dependencies
:: =============================================
echo [3/5] 检查并安装依赖（requests pyyaml fastapi uvicorn scapy）...
pip install requests pyyaml fastapi uvicorn scapy -q
if %errorlevel% neq 0 (
    echo.
    echo [提示] 依赖安装出现问题，继续执行；诊断脚本会报告具体缺失项
    echo.
)
echo    依赖检查完成
echo.

:: =============================================
:: Step 4: Run test_remote.py
:: =============================================
echo [4/5] 运行单元 + 集成测试 test_remote.py...
echo --------------------------------------------
python test_remote.py
set TEST_RC=%errorlevel%
echo --------------------------------------------
echo.

:: =============================================
:: Step 5: Run diagnose_remote.py
:: =============================================
echo [5/5] 运行本机链路在线诊断 diagnose_remote.py...
echo --------------------------------------------
python diagnose_remote.py
set DIAG_RC=%errorlevel%
echo --------------------------------------------
echo.

:: =============================================
:: Summary
:: =============================================
echo ============================================
echo   汇总
echo ============================================
if "%TEST_RC%"=="0" (
    echo   测试 test_remote.py      : PASS  (rc=%TEST_RC%)
) else (
    echo   测试 test_remote.py      : FAIL  (rc=%TEST_RC%)
)
if "%DIAG_RC%"=="0" (
    echo   诊断 diagnose_remote.py  : PASS  (rc=%DIAG_RC%, WARN 不算失败)
) else (
    echo   诊断 diagnose_remote.py  : 有 FAIL  (rc=%DIAG_RC%)
)
echo.
echo   日志目录: logs\
echo     - 测试日志: logs\test_remote_*.log
echo     - 诊断日志: logs\diagnose_remote_*.log
echo   （在 logs\ 目录按修改时间取最新的两个文件即可）
echo.

pause
