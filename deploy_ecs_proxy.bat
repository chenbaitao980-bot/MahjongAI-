@echo off
setlocal
python "%~dp0scripts\deploy_ecs_proxy.py" %*
echo.
echo ============================================================
echo Done. Now play a round in-game, then run diag_ecs.bat.
echo ============================================================
pause
endlocal
