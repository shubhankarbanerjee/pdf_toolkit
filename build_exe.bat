@echo off
echo ============================================================
echo   PDF Toolkit - Build Standalone Executable
echo ============================================================
echo.
echo This script will create a standalone .exe file that you can
echo distribute and run without installing Python.
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    pause
    exit /b 1
)

REM Install PyInstaller if not present
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

echo.
echo Building executable...
echo.

REM Build the executable
pyinstaller --onefile ^
    --name "PDF-Toolkit" ^
    --icon=NONE ^
    --add-data "templates;templates" ^
    --add-data "requirements.txt;." ^
    --hidden-import flask ^
    --hidden-import fitz ^
    --hidden-import pypdf ^
    --hidden-import PyPDF2 ^
    --hidden-import PIL ^
    --hidden-import pytesseract ^
    --console ^
    desktop_app.py

echo.
echo ============================================================
if exist dist\PDF-Toolkit.exe (
    echo SUCCESS! Executable created: dist\PDF-Toolkit.exe
    echo.
    echo You can now distribute this .exe file.
    echo Note: Users will still need Tesseract OCR installed for OCR functions.
) else (
    echo Build may have failed. Check the output above.
)
echo ============================================================
echo.
pause