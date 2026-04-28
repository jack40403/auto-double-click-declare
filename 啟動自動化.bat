@echo off
title Pharmacy Automation Launcher
cd /d "%~dp0"

echo [1/2] Checking Python Environment...
set "PYTHON_EXE=python"
python --version >nul 2>&1
if errorlevel 1 (
    py --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python not found. Please install Python and check 'Add to PATH'.
        pause
        exit /b 1
    )
    set "PYTHON_EXE=py"
)

echo [2/2] Preparing Environment...
:: --- Checking if environment is functional ---
set "REBUILD=0"
if not exist "venv\Scripts\python.exe" set "REBUILD=1"
if exist "venv\Scripts\python.exe" (
    .\venv\Scripts\python.exe -c "import sys; print('check')" >nul 2>&1
    if errorlevel 1 set "REBUILD=1"
)

if "%REBUILD%"=="1" (
    echo [Environment] Setting up or repairing virtual environment...
    if exist "venv" (
        echo [Fix] Existing environment is broken or moved. Cleaning up...
        rmdir /s /q venv >nul 2>&1
    )
    %PYTHON_EXE% -m venv venv
    if errorlevel 1 (
        echo [Error] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [Environment] Installing dependencies...
    .\venv\Scripts\python.exe -m pip install --upgrade pip
    .\venv\Scripts\pip.exe install -r requirements.txt
)

echo Note: If it's the first time running on this PC, it may take a moment to load.
.\venv\Scripts\python.exe Main_App.pyw

if errorlevel 1 (
    echo.
    echo [ERROR] Application closed unexpectedly.
    pause
    exit /b 1
)

echo.
echo [DONE] The launcher has finished its task.
echo Note: If a UAC prompt (Admin permission) appeared, please click 'Yes' to open the app.
pause
exit
