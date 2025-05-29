@echo off
REM Change directory to the project root (parent of this script's location)
echo Navigating to project root...
cd /D "%~dp0..\"

echo Current directory: %CD%
echo.

echo Checking for Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python is not installed or not in PATH. Please install Python and add it to PATH.
    pause
    exit /b 1
)

echo Creating virtual environment 'venv' in project root if it doesn't exist...
if not exist venv\ (
    python -m venv venv
    if %errorlevel% neq 0 (
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo Virtual environment created.
) else (
    echo Virtual environment 'venv' already exists.
)

echo Activating virtual environment and installing requirements...
call venv\Scripts\activate.bat

echo Installing packages from requirements.txt (expected in project root)...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo Failed to install requirements. Make sure requirements.txt is present in project root and correct.
    pause
    exit /b 1
)

echo.
echo Setup complete! The virtual environment 'venv' is ready and requirements are installed.
echo You can now run 'build_exe.bat' from the '%~dp0' folder.
pause
exit /b 0