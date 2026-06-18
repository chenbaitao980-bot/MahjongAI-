@echo off
setlocal
chcp 65001 >nul 2>&1

:: =============================================
:: ECS Failover Drill: START services
::
:: Restarts the ECS systemd services that
:: stop_ecs_services.bat brought down. This brings
:: the noconfig pipeline back online so the phone
:: re-routes to ECS on the next connection.
::
:: This script ONLY runs systemctl start on the
:: server. It DOES NOT deploy / scp / modify code
:: on the ECS box. See: server-readonly-git-sync
:: discipline in CLAUDE.md.
:: =============================================

set ECS_HOST=root@8.136.37.136

echo ============================================
echo   START ECS services after failover drill
echo   Target: %ECS_HOST%
echo ============================================
echo.

ssh -V >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] SSH not available. Install OpenSSH or use Git Bash.
    pause
    exit /b 1
)

echo [1/2] systemctl start on ECS ...
ssh %ECS_HOST% "systemctl start mahjong-mitm-hotupdate mahjong-tcp-proxy mahjong-relay-noconfig 2>&1; systemctl start mjx-vpn 2>/dev/null; systemctl is-active mahjong-mitm-hotupdate mahjong-tcp-proxy mahjong-relay-noconfig mjx-vpn 2>&1"
if %errorlevel% neq 0 (
    echo [WARN] systemctl reported non-zero. Check logs:
    echo        ssh %ECS_HOST% "journalctl -u mahjong-mitm-hotupdate -n 30"
)
echo.

echo [2/2] Probe ECS public ports (expect success) ...
echo.
echo   - HTTPS hotupdate MITM (TCP/443):
curl --max-time 5 -ksS -o NUL -w "     status=%%{http_code} time=%%{time_total}s\n" https://8.136.37.136:443/ 2>&1
echo.
echo   - noconfig relay (TCP/8002):
curl --max-time 5 -sS -o NUL -w "     status=%%{http_code} time=%%{time_total}s\n" http://8.136.37.136:8002/ 2>&1
echo.
echo   - SRS lobby + game proxy listeners:
ssh %ECS_HOST% "ss -ltn | grep -E ':5748|:5749|:5767|:5768|:443|:8002' || echo     none listening"
echo.

echo ============================================
echo   ECS services started.
echo.
echo   Next: re-open the game on the phone
echo     1. Verify relay/spectator picks up tiles
echo        again (= ECS path is reached)
echo     2. Tail relay log to confirm:
echo        ssh %ECS_HOST% "journalctl -u mahjong-relay-noconfig -n 20"
echo ============================================

endlocal
