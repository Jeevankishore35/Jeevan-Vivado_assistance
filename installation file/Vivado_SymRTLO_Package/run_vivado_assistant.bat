@echo off
title Vivado AI Assistant - Interactive Text Console
color 0B

if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

python vivado_assistant_cli.py %*

if %errorlevel% neq 0 (
    echo.
    echo ======================================================================
    echo [!] Program exited.
    echo ======================================================================
    pause
)
