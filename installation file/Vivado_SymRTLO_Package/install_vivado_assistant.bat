@echo off
title SymRTLO Vivado Assistant - 1-Click Installer
color 0A

echo ======================================================================
echo             SymRTLO VIVADO ASSISTANT - 1-CLICK INSTALLER
echo ======================================================================
echo.

REM 1. Check Python
echo [Step 1/3] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python 3.10+ and check "Add Python to PATH".
    pause
    exit /b 1
)
python --version
echo.

REM 2. Create virtual environment
echo [Step 2/3] Setting up Python virtual environment...
if not exist venv (
    python -m venv venv
)
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)
echo.

REM 3. Install packages
echo [Step 3/3] Installing Z3 SMT Solver and AI packages...
pip install --upgrade pip --quiet
pip install -r requirements.txt

echo.
echo ======================================================================
echo               SYMRTLO INSTALLATION COMPLETED!
echo ======================================================================
echo You can now run optimization with "run_vivado_assistant.bat" or:
echo python symrtlo_cli.py --input examples/adder_subexpression.v --goal area
echo.
pause
