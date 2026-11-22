@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1

if not exist "docs\index.html" (
    if exist ".venv\Scripts\python.exe" (
        ".venv\Scripts\python.exe" src\build_site.py
    ) else (
        echo [エラー] docs\index.html が見つかりません。先に run_today_radio.bat を実行してください。
        pause
        exit /b 1
    )
)

start "" "%~dp0docs\index.html"
exit /b 0
