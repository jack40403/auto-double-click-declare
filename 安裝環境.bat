@echo off
setlocal
title 藥局自動化 - 環境安裝程式
cd /d "%~dp0"

echo ==========================================
echo    藥局自動化系統 - 環境一鍵安裝包
echo ==========================================
echo.

:: 檢查 Python 是否安裝
set "PYTHON_EXE=python"
python --version >nul 2>&1
if %errorlevel% neq 0 (
    py --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo [錯誤] 找不到 Python！請先安裝 Python 3.8 或以上版本。
        echo 請前往 https://www.python.org/downloads/ 下載安裝，並勾選 "Add Python to PATH"。
        pause
        exit /b 1
    )
    set "PYTHON_EXE=py"
)

:: 建立虛擬環境
if not exist "venv" (
    echo [1/3] 正在建立虛擬環境 (venv)...
    %PYTHON_EXE% -m venv venv
    if %errorlevel% neq 0 (
        echo [錯誤] 建立虛擬環境失敗。
        pause
        exit /b 1
    )
) else (
    echo [1/3] 虛擬環境已存在，跳過建立。
)

:: 升級 pip 並安裝套件
echo [2/3] 正在安裝依附套件 (這可能需要幾分鐘，請稍候)...
echo 提示：EasyOCR 與 OpenCV 檔案較大，請保持網路連線。
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\pip.exe install -r requirements.txt

if %errorlevel% neq 0 (
    echo.
    echo [警告] 套件安裝過程中出現一些問題。請檢查網路連線後重試。
    pause
    exit /b 1
)

echo [3/3] 環境安裝完成！
echo.
echo ==========================================
echo    現在您可以執行「啟動自動化.bat」來使用程式。
echo ==========================================
echo.
pause
