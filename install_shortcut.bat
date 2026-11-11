@echo off
chcp 65001 >nul
REM デスクトップとスタートメニューに「Unified File Search」のショートカットを作成します
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo 先に run.bat を一度実行して、環境を準備してください。
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\create_shortcut.ps1"
pause
