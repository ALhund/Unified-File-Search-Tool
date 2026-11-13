@echo off
chcp 65001 >nul
REM ライセンスコード生成ツール（販売者専用。購入者には渡さないでください）
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo 先に run.bat を一度実行して、環境を準備してください。
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0tools\license_generator.py"
