@echo off
REM 本地热更 MITM 启动脚本（Windows）
REM 需要以管理员身份运行

echo ============================================
echo   本地热更 MITM 启动脚本
echo ============================================
echo.

REM 检查管理员权限
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] 需要以管理员身份运行
    echo 请右键此脚本，选择"以管理员身份运行"
    pause
    exit /b 1
)

REM 设置参数
set HOST_IP=192.168.137.1
set ECS_IP=8.136.37.136

echo 配置:
echo   PC 热点 IP: %HOST_IP%
echo   ECS IP: %ECS_IP%
echo.

REM 检查 APK
if not exist "apk\game_base.apk" (
    echo [ERROR] APK 不存在: apk\game_base.apk
    echo 请把游戏 APK 放到该位置
    pause
    exit /b 1
)

REM 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 未安装或不在 PATH
    pause
    exit /b 1
)

echo 启动热更 MITM 服务...
echo.
echo 使用步骤:
echo   1. 手机连 PC 热点
echo   2. 打开游戏，等待热更
echo   3. 看到日志 "NetConf.luac" 下载成功后，手机断热点
echo   4. 之后任意网络都能读牌
echo.
echo 按 Ctrl+C 停止服务
echo.

python remote\noconfig\hijack\run_hijack.py --host-ip %HOST_IP% --ecs-ip %ECS_IP%

pause