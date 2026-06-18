@echo off
setlocal
chcp 65001 >nul 2>&1

:: =============================================
:: ECS Failover Drill: STOP services
::
:: Stops ECS systemd services so we can verify the
:: client-side Path Y failover (NetConf 5045 list
:: containing real-server entries + NetEngine
:: fail-count rotation) routes the phone back to
:: the real production servers when ECS is down.
::
:: This script ONLY runs systemctl stop on the
:: server. It DOES NOT deploy / scp / modify code
:: on the ECS box. See: server-readonly-git-sync
:: discipline in CLAUDE.md.
:: =============================================

set ECS_HOST=root@8.136.37.136

echo ============================================
echo   STOP ECS services for failover drill
echo   Target: %ECS_HOST%
echo ============================================
echo.

ssh -V >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] SSH not available. Install OpenSSH or use Git Bash.
    pause
    exit /b 1
)

echo [1/2] systemctl stop on ECS ...
ssh %ECS_HOST% "systemctl stop mahjong-mitm-hotupdate mahjong-tcp-proxy mahjong-relay-noconfig mjx-vpn 2>&1; systemctl is-active mahjong-mitm-hotupdate mahjong-tcp-proxy mahjong-relay-noconfig mjx-vpn 2>&1"
if %errorlevel% neq 0 (
    echo [WARN] systemctl reported non-zero (some services may already be down).
)
echo.

echo [2/2] Probe ECS public ports (expect failures) ...
echo.
echo   - HTTPS hotupdate MITM (TCP/443):
curl --max-time 3 -ksS -o NUL -w "     status=%%{http_code} time=%%{time_total}s\n" https://8.136.37.136:443/ 2>&1
echo.
echo   - noconfig relay (TCP/8002):
curl --max-time 3 -sS -o NUL -w "     status=%%{http_code} time=%%{time_total}s\n" http://8.136.37.136:8002/ 2>&1
echo.
echo   - SRS lobby proxy (TCP/5748):
ssh %ECS_HOST% "ss -ltn | grep -E ':5748|:5749|:5767|:5768' || echo     all closed"
echo.

echo ============================================
echo   ECS services stopped.
echo.
echo   Next: drill on the phone (4G or another WiFi)
echo     1. Reopen the game
echo     2. Verify lobby loads (NetConf 5045 list
echo        rotates to real server when ECS fails)
echo     3. Verify coin game loads (NetConf _50
echo        list[2] = real server is reached)
echo.
echo   When done, run start_ecs_services.bat to
echo   bring ECS back online.
echo ============================================

endlocal
