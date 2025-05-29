@echo off
REM Change directory to the project root (parent of this script's location)
echo Navigating to project root...
cd /D "%~dp0..\"

echo Current directory: %CD%
echo.

echo Activating virtual environment...
if not exist venv\Scripts\activate.bat (
    echo Virtual environment not found in project root. Please run setup_env.bat first.
    pause
    exit /b 1
)
call venv\Scripts\activate.bat

echo Starting PyInstaller build...

REM --- IMPORTANT: ICON PATH ---
REM Ensure 'your_app_icon.ico' path is correct relative to the project root.
REM If your icon is in the project root: --icon="your_app_icon.ico"
REM If your icon is in 'assets' folder: --icon="assets\your_app_icon.ico"
REM If you don't have an icon, remove the --icon="..." part.
set ICON_PATH=app_icon.ico
REM Example if icon is in assets: set ICON_PATH=assets\app_icon.ico

pyinstaller --name "BatchDownloader" --onefile --windowed --icon="%ICON_PATH%" --add-data "assets;assets" --add-data "drivers;drivers" app.py

if %errorlevel% neq 0 (
    echo PyInstaller build failed.
    pause
    exit /b 1
)

echo.
echo PyInstaller build successful!
echo Executable is in the 'dist' folder (relative to project root).
pause
exit /b 0