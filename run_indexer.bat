@echo off
setlocal enabledelayedexpansion
title Medical Literature Indexer - Launcher

echo ============================================================
echo      Medical Literature Search - Windows Indexer
echo ============================================================
echo.

cd /d "%~dp0"

:: 1. Check Python
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python is not found in your system PATH.
    echo Please install Python 3.12+ from https://www.python.org/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

:: 2. Check Virtual Environment
if not exist "venv\Scripts\activate.bat" (
    echo [INFO] Virtual environment not found. Creating 'venv'...
    python -m venv venv
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    call venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate.bat
)

python -c "import docx, pymupdf, zstandard" >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [INFO] Installing missing dependencies...
    pip install -r requirements.txt
)

:: 3. Launch App
echo [INFO] Launching Desktop Application...
python -m indexer.main %*

if %ERRORLEVEL% neq 0 (
    echo.
    echo [WARNING] Application closed with code %ERRORLEVEL%.
    pause
)
