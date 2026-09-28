@echo off
title Voice Assistant Setup - Auto Installer
color 0A

echo ======================================================================
echo           WINDOWS VOICE AUTOMATION - 1-CLICK INSTALLER
echo ======================================================================
echo.

REM 1. Check if Python is installed
echo [Step 1/4] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo [ERROR] Python is NOT installed or NOT added to PATH!
    echo.
    echo Please install Python 3.10 or higher from https://www.python.org/downloads/
    echo IMPORTANT: Make sure to check the box "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

python --version
echo [OK] Python is detected.
echo.

REM 2. Create / Check Python Virtual Environment
echo [Step 2/4] Setting up dedicated Python virtual environment (venv)...
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [WARNING] Failed to create virtual environment. Installing packages globally...
    ) else (
        echo [OK] Virtual environment created successfully.
    )
) else (
    echo [OK] Virtual environment already exists.
)
echo.

REM 3. Activate Virtual Environment
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

REM 4. Upgrade pip and install dependencies
echo [Step 3/4] Upgrading pip...
python -m pip install --upgrade pip --quiet

echo.
echo [Step 4/4] Installing required Python libraries from requirements.txt...
echo (This may take 1-3 minutes depending on internet speed)
echo.
pip install -r requirements.txt

if %errorlevel% neq 0 (
    echo.
    echo [INFO] Retrying audio dependencies installation (pyaudio wheel fallback)...
    pip install pipwin --quiet
    pipwin install pyaudio
    pip install -r requirements.txt
)

echo.
echo ======================================================================
echo                       INSTALLATION COMPLETED!
echo ======================================================================
echo.
echo Setup is complete and ready to run.
echo.
echo HOW TO RUN:
echo   - Double-click "start.bat" to launch the voice assistant.
echo.
echo HELPFUL TIPS:
echo   - To pause/resume listening at any time: Press [Ctrl + H]
echo   - To stop the assistant: Press [Ctrl + Alt + H]
echo   - To customize commands or add a Gemini API key: Edit "commands.json"
echo.
echo ======================================================================
echo.
pause
