@echo off
title PDF Toolkit - Desktop Application
echo ============================================================
echo   PDF Toolkit - Desktop Application
echo ============================================================
echo.
echo This application runs entirely on your computer.
echo No data is sent to any server or over the internet.
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python from https://www.python.org/
    echo.
    pause
    exit /b 1
)

echo Python found!
echo.

REM Check if we're in a virtual environment
if not defined VIRTUAL_ENV (
    echo Setting up virtual environment...
    python -m venv venv
    call venv\Scripts\activate.bat
    echo Installing dependencies...
    pip install -r requirements.txt
) else (
    echo Using existing virtual environment
)

echo.
echo Starting PDF Toolkit...
echo.

REM Run the desktop application
python desktop_app.py

pause