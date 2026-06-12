@echo off
setlocal
cd /d "%~dp0"

:: =============================================
::  一键部署到 ECS 云端
::  将项目文件打包上传到 ECS 并执行部署脚本
:: =============================================

echo ============================================
echo   MahjongAI - ECS 云端一键部署
echo   目标: 8.136.37.136
echo ============================================
echo.

set ECS_HOST=root@8.136.37.136

:: 检查 SSH 是否可用
ssh -V >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] SSH 不可用. 请安装 OpenSSH 或使用 Git Bash.
    echo   Windows: 设置→应用→可选功能→添加 OpenSSH 客户端
    pause
    exit /b 1
)

echo [1/3] 打包项目文件...
:: 创建临时 tar 包（排除 .git, .venv, __pycache__, logs 等）
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
    echo [ERROR] 打包失败.
    pause
    exit /b 1
)
echo    打包完成: ecs-update.tar
echo.

echo [2/3] 上传到 ECS...
scp ecs-update.tar %ECS_HOST%:/tmp/mahjong-update.tar
if %errorlevel% neq 0 (
    echo [ERROR] 上传失败. 请检查 SSH 连接.
    pause
    exit /b 1
)
echo    上传完成.
echo.

echo [3/3] 在 ECS 上执行部署...
ssh %ECS_HOST% "cd /tmp && mkdir -p mahjong-deploy && cd mahjong-deploy && tar -xf /tmp/mahjong-update.tar && bash deploy_ecs.sh"
if %errorlevel% neq 0 (
    echo [WARN] 部署脚本执行有问题, 请检查 ECS 上的日志.
)
echo.

echo ============================================
echo   部署完成!
echo.
echo   验证命令:
echo     ssh %ECS_HOST% "curl -s http://localhost:8000/mode"
echo     ssh %ECS_HOST% "curl -s http://localhost:8001/mode"
echo     ssh %ECS_HOST% "curl -s http://localhost:8002/mode"
echo.
echo   查看服务状态:
echo     ssh %ECS_HOST% "systemctl status mahjong-relay-hotspot"
echo     ssh %ECS_HOST% "systemctl status mahjong-relay-vpn"
echo     ssh %ECS_HOST% "systemctl status mahjong-relay-noconfig"
echo ============================================
echo.

pause
endlocal
