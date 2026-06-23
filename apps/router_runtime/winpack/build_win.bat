@echo off
REM build_win.bat - Build the Windows tray exe (PyInstaller one-folder).
REM Pure ASCII only (cmd.exe mis-parses non-ASCII line bytes). Run from anywhere;
REM this script cd's to apps/router_runtime (its parent dir) first.

setlocal
cd /d "%~dp0.."

echo ============================================
echo   MahjongMITM Windows tray build
echo ============================================
echo.

echo [1/4] Checking dependencies...
python -c "import PyInstaller, pydivert, winsdk, pystray, PIL, cryptography, requests" 2>nul
if %errorlevel% neq 0 (
    echo   Installing windows extras + pyinstaller...
    python -m pip install pyinstaller "pydivert>=2.1" "pystray>=0.19" "Pillow>=9.0" "winsdk==1.0.0b10" "cryptography>=3.4" "requests>=2.25"
    if %errorlevel% neq 0 (
        echo [ERROR] dependency install failed.
        pause
        exit /b 1
    )
)
echo Done.
echo.

echo [2/4] Checking embedded APK...
if not exist "assets\game_base.apk" (
    echo [ERROR] assets\game_base.apk not found. Place the game APK there first.
    pause
    exit /b 1
)
echo   assets\game_base.apk present.
echo.

echo [3/4] Cleaning old build...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
echo Done.
echo.

echo [4/4] Running PyInstaller...
pyinstaller winpack\mahjong_mitm_win.spec
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] PyInstaller failed. Check output above.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Build complete.
echo   Output : dist\MahjongMITM\MahjongMITM.exe
echo   Distribute: zip the whole dist\MahjongMITM\ folder.
echo   Run: double-click MahjongMITM.exe (UAC will prompt for admin).
echo ============================================
echo.
pause
endlocal
