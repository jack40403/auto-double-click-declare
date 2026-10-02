@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title 藥局自動化 - 環境檢查與啟動

echo [1/3] 檢查 Python 與程式套件...
if not exist "venv\Scripts\python.exe" goto RebuildEnvironment

"venv\Scripts\python.exe" -c "import sys" >nul 2>&1
if errorlevel 1 goto RebuildEnvironment

"venv\Scripts\python.exe" -c "import pyautogui, keyboard, customtkinter, easyocr, cv2, numpy, PIL, pygetwindow, win32gui, win32con, win32com.client, bs4" >nul 2>&1
if errorlevel 1 goto InstallDependencies
goto EnvironmentReady

:RebuildEnvironment
echo [環境] Python 虛擬環境不存在或無法使用，準備重建...
call :FindPython
if errorlevel 1 goto PythonMissing

if exist "venv" (
    rmdir /s /q "venv"
    if exist "venv" goto EnvironmentCleanupFailed
)

echo [環境] 建立虛擬環境...
%PYTHON_EXE% -m venv "venv"
if errorlevel 1 goto EnvironmentCreateFailed
goto InstallDependencies

:InstallDependencies
echo [2/3] 安裝或修復程式套件，請保持網路連線...
"venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto DependencyInstallFailed
"venv\Scripts\python.exe" -m pip install -r "requirements.txt"
if errorlevel 1 goto DependencyInstallFailed

"venv\Scripts\python.exe" -c "import pyautogui, keyboard, customtkinter, easyocr, cv2, numpy, PIL, pygetwindow, win32gui, win32con, win32com.client, bs4" >nul 2>&1
if errorlevel 1 goto DependencyCheckFailed

:EnvironmentReady
echo [完成] 執行環境已就緒。

echo [3/3] 啟動藥局自動化...
"venv\Scripts\python.exe" "Main_App.pyw"
if errorlevel 1 goto ApplicationFailed
exit /b 0

:FindPython
set "PYTHON_EXE="
set "PYTHON_HOME="

if exist "venv\pyvenv.cfg" (
    for /f "tokens=1,* delims== " %%A in ('findstr /i /b "home =" "venv\pyvenv.cfg"') do if /i "%%A"=="home" set "PYTHON_HOME=%%B"
)
if defined PYTHON_HOME (
    if exist "%PYTHON_HOME%\python.exe" (
        "%PYTHON_HOME%\python.exe" -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>&1
        if not errorlevel 1 (
            set "PYTHON_EXE="%PYTHON_HOME%\python.exe""
            exit /b 0
        )
    )
)

for %%V in (3.14 3.13 3.12 3.11 3.10) do (
    py -%%V -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=py -%%V"
        exit /b 0
    )
)

python -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=python"
    exit /b 0
)

where.exe winget >nul 2>&1
if errorlevel 1 exit /b 1
echo [環境] 找不到 Python，使用 Windows 套件管理員安裝 Python 3.12...
winget install --id Python.Python.3.12 -e --scope user --silent --accept-source-agreements --accept-package-agreements
if errorlevel 1 exit /b 1

set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE="%PYTHON_EXE%""
        exit /b 0
    )
)
py -3.12 -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=py -3.12"
    exit /b 0
)
exit /b 1

:PythonMissing
echo [錯誤] 無法自動安裝 Python。請安裝 Python 3.10 以上版本，並重新執行本檔。
echo 若此電腦沒有 winget，請從 https://www.python.org/downloads/windows/ 安裝 Python。
goto Failed

:EnvironmentCleanupFailed
echo [錯誤] 無法移除失效的 venv 環境，請確認沒有其他程式正在使用它。
goto Failed

:EnvironmentCreateFailed
echo [錯誤] 建立 venv 失敗，請確認磁碟空間與 Python 安裝狀態。
goto Failed

:DependencyInstallFailed
echo [錯誤] 套件安裝失敗。請檢查網路連線後重新執行本檔。
goto Failed

:DependencyCheckFailed
echo [錯誤] 安裝後仍無法載入必要套件；請查看上方錯誤並重新執行本檔。
goto Failed

:ApplicationFailed
echo [錯誤] 程式啟動失敗，詳細紀錄請查看 debug_log.txt。
goto Failed

:Failed
pause
exit /b 1
