@echo off
chcp 65001 >nul
echo ========================================
echo  ECS MITM 代理部署脚本
echo ========================================
echo.

set ECS_IP=8.136.37.136
set ECS_USER=root
set ECS_PASS=Ysydxhyz111
set REMOTE_DIR=/opt/mahjong-mitm

echo [1/5] 创建远程目录...
ssh -o StrictHostKeyChecking=no %ECS_USER%@%ECS_IP% "mkdir -p %REMOTE_DIR%" || goto :error

echo [2/5] 同步代码到远程...
scp -o StrictHostKeyChecking=no -r remote\noconfig\hijack\*.py %ECS_USER%@%ECS_IP%:%REMOTE_DIR%/ || goto :error
scp -o StrictHostKeyChecking=no -r remote\srs_spectator\*.py %ECS_USER%@%ECS_IP%:%REMOTE_DIR%/ || goto :error
scp -o StrictHostKeyChecking=no -r stable\*.py %ECS_USER%@%ECS_IP%:%REMOTE_DIR%/ || goto :error

echo [3/5] 检查远程 Python 环境...
ssh -o StrictHostKeyChecking=no %ECS_USER%@%ECS_IP% "python3 --version && pip3 list | grep -i cryptography" || goto :error

echo [4/5] 停止旧服务...
ssh -o StrictHostKeyChecking=no %ECS_USER%@%ECS_IP% "pkill -f 'ecs_run.py' 2>/dev/null; pkill -f 'tcp_proxy.py' 2>/dev/null; echo '旧服务已停止'" || goto :error

echo [5/5] 启动新服务...
ssh -o StrictHostKeyChecking=no %ECS_USER%@%ECS_IP% "cd %REMOTE_DIR% && nohup python3 ecs_run.py --ecs-ip %ECS_IP% --relay-url http://localhost:8002 > /var/log/mahjong-mitm.log 2>&1 &" || goto :error

echo.
echo ========================================
echo  部署完成！
echo  服务日志: ssh %ECS_USER%@%ECS_IP% "tail -f /var/log/mahjong-mitm.log"
echo ========================================
goto :end

:error
echo.
echo [ERROR] 部署失败！
exit /b 1

:end
pause
