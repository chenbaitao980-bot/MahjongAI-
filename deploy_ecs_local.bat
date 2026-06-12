@echo off
setlocal
chcp 65001 >nul 2>&1

:: =============================================
::  Deploy to ECS Cloud Server
::  Package -> Upload -> SSH deploy
:: =============================================

echo ============================================
echo   MahjongAI - ECS Cloud Deploy
echo   Target: 8.136.37.136
echo ============================================
echo.

set ECS_HOST=root@8.136.37.136

:: Check SSH
ssh -V >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] SSH not available. Install OpenSSH or use Git Bash.
    pause
    exit /b 1
)

echo [1/3] Packaging project files ...
tar -cf ecs-update.tar ^
    --exclude=".git" ^
    --exclude=".venv" ^
    --exclude="venv" ^
    --exclude="__pycache__" ^
    --exclude="*.pyc" ^
    --exclude="logs" ^
    --exclude="dist" ^
    --exclude="build" ^
    --exclude=".obsidian" ^
    --exclude=".trellis" ^
    --exclude=".claude" ^
    --exclude="*.spec" ^
    remote/ stable/ game/ config/ deploy_ecs.sh e2e_test.py

if %errorlevel% neq 0 (
    echo [ERROR] Package failed.
    pause
    exit /b 1
)
echo    Package done: ecs-update.tar
echo.

echo [2/3] Uploading to ECS ...
scp ecs-update.tar %ECS_HOST%:/tmp/mahjong-update.tar
if %errorlevel% neq 0 (
    echo [ERROR] Upload failed. Check SSH connection.
    pause
    exit /b 1
)
echo    Upload done.
echo.

echo [3/3] Running deploy script on ECS ...
ssh %ECS_HOST% "cd /tmp && mkdir -p mahjong-deploy && cd mahjong-deploy && tar -xf /tmp/mahjong-update.tar && bash deploy_ecs.sh"
if %errorlevel% neq 0 (
    echo [WARN] Deploy script had issues, check ECS logs.
)
echo.

echo ============================================
echo   Deploy Complete!
echo.
echo   Verify:
echo     ssh %ECS_HOST% "curl -s http://localhost:8000/mode"
echo     ssh %ECS_HOST% "curl -s http://localhost:8001/mode"
echo     ssh %ECS_HOST% "curl -s http://localhost:8002/mode"
echo ============================================
echo.

pause
endlocal
