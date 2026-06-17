@echo off
setlocal
python "%~dp0scripts\restart_hotspot_mitm_and_ecs.py" %*
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Script exited with code %ERRORLEVEL%
    echo.
)
endlocal
pause
