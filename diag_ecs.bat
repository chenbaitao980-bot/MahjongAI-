@echo off
setlocal
python "%~dp0scripts\diag_ecs.py" %*
echo.
echo ============================================================
echo Diagnosis done. Paste the output above back to Claude.
echo ============================================================
pause
endlocal
