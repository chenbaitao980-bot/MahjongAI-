@echo off
cd /d "%~dp0"

echo ============================================
echo  MahjongAI Build Script
echo ============================================
echo.

echo [1/4] Cleaning old build...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
echo Done.
echo.

echo [2/4] Running PyInstaller...
pyinstaller mahjong_ai.spec

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] PyInstaller failed. Check the output above.
    pause
    exit /b 1
)

echo.
echo [3/4] Copying sample data...

set DEST=dist\MahjongAI\data
if not exist "%DEST%" mkdir "%DEST%"

if exist data\tile_samples_cleaned (
    echo   tile_samples_cleaned
    xcopy /E /I /Y /Q "data\tile_samples_cleaned" "%DEST%\tile_samples_cleaned" >nul
)

if exist data\tile_samples_discard_cleaned (
    echo   tile_samples_discard_cleaned
    xcopy /E /I /Y /Q "data\tile_samples_discard_cleaned" "%DEST%\tile_samples_discard_cleaned" >nul
)

if exist data\tile_samples (
    echo   tile_samples
    xcopy /E /I /Y /Q "data\tile_samples" "%DEST%\tile_samples" >nul
)

if exist data\event_samples (
    echo   event_samples
    xcopy /E /I /Y /Q "data\event_samples" "%DEST%\event_samples" >nul
)

if exist data\layout_reference (
    echo   layout_reference
    xcopy /E /I /Y /Q "data\layout_reference" "%DEST%\layout_reference" >nul
)

if exist data\event_reference (
    echo   event_reference
    xcopy /E /I /Y /Q "data\event_reference" "%DEST%\event_reference" >nul
)

echo Done.
echo.

echo [4/4] Build complete!
echo.
echo Output : %~dp0dist\MahjongAI\
echo Run    : %~dp0dist\MahjongAI\MahjongAI.exe
echo.
echo Distribute: zip the dist\MahjongAI\ folder and share it.
echo.
pause
