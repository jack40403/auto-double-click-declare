@echo off
setlocal
title 藥局自動化 - 一鍵安裝並啟動
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo [偵測] 尚未安裝環境，準備開始自動安裝...
    call "安裝環境.bat"
)

if exist "venv\Scripts\python.exe" (
    echo.
    echo [啟動] 環境已就緒，正在啟動程式...
    call "啟動自動化.bat"
) else (
    echo.
    echo [錯誤] 無法啟動，環境安裝可能未成功。
    pause
)
