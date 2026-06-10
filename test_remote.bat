@echo off
cd /d "%~dp0"

echo ============================================
echo   MahjongAI Remote - Test + Diagnose
echo ============================================
echo.

:: =============================================
:: Step 1: Check Python
:: =============================================
echo [1/5] Checking Python environment...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Python not found. Please install Python 3.8+.
    echo         Download: https://www.python.org/downloads/
    echo         During install, check "Add Python to PATH".
    echo.
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do echo    Python %%v
echo.

:: =============================================
:: Step 2: Activate venv (if present)
:: =============================================
echo [2/5] Checking virtual environment...
if exist "venv\Scripts\python.exe" (
    call "venv\Scripts\activate.bat"
    echo    Activated project venv.
) else (
    echo    [NOTE] venv not found, using system Python.
)
echo.

:: =============================================
:: Step 3: Ensure dependencies
:: =============================================
echo [3/5] Installing dependencies (requests pyyaml fastapi uvicorn scapy)...
pip install requests pyyaml fastapi uvicorn scapy -q
if %errorlevel% neq 0 (
    echo.
    echo [NOTE] Dependency install had problems; continuing.
    echo        The diagnose script will report any missing items.
    echo.
)
echo    Dependency check done.
echo.

:: =============================================
:: Step 4: Run test_remote.py
:: =============================================
echo [4/5] Running unit + integration tests (test_remote.py)...
echo --------------------------------------------
python test_remote.py
set TEST_RC=%errorlevel%
echo --------------------------------------------
echo.

:: =============================================
:: Step 5: Run diagnose_remote.py
:: =============================================
echo [5/5] Running local link diagnose (diagnose_remote.py)...
echo --------------------------------------------
python diagnose_remote.py
set DIAG_RC=%errorlevel%
echo --------------------------------------------
echo.

:: =============================================
:: Summary
:: =============================================
echo ============================================
echo   Summary
echo ============================================
if "%TEST_RC%"=="0" (
    echo   test_remote.py      : PASS  (rc=%TEST_RC%)
) else (
    echo   test_remote.py      : FAIL  (rc=%TEST_RC%)
)
if "%DIAG_RC%"=="0" (
    echo   diagnose_remote.py  : PASS  (rc=%DIAG_RC%, WARN is not a failure)
) else (
    echo   diagnose_remote.py  : FAIL  (rc=%DIAG_RC%)
)
echo.
echo   Log directory: logs\
echo     - Test log:     logs\test_remote_*.log
echo     - Diagnose log: logs\diagnose_remote_*.log
echo   (Pick the two newest files by modified time in logs\)
echo.

pause
