@echo off
title AI Assistant Console - Interactive Launcher
color 0B

echo ======================================================================
echo                     AI ASSISTANT LAUNCHER
echo ======================================================================
echo.

REM 1. Activate virtual environment if present
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

echo Choose your preferred interface:
echo   [1] Text Prompt Console (Primary / Recommended)
echo   [2] Vivado AI Assistant & RTL Optimizer (Interactive Chat)
echo   [3] Voice Listening Mode (Optional - Requires Microphone)
echo.
set /p MODE="Select mode (1, 2, or 3 - default 1): "

if "%MODE%"=="" set MODE=1

if "%MODE%"=="1" (
    python voice_control.py --text
) else if "%MODE%"=="2" (
    cd Vivado_SymRTLO_Package
    python vivado_assistant_cli.py
    cd ..
) else if "%MODE%"=="3" (
    echo.
    echo [System]: Starting Voice Assistant...
    echo [System]: Press Ctrl+H to pause/resume listening.
    echo [System]: Press Ctrl+Alt+H to quit safely.
    echo.
    python voice_control.py
) else (
    python voice_control.py --text
)

if %errorlevel% neq 0 (
    echo.
    echo ======================================================================
    echo [!] Session exited.
    echo ======================================================================
    pause
)
