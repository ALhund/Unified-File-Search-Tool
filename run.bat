@echo off
chcp 65001 >nul
REM Unified File Search 起動バッチ（初回は環境を自動で準備します）

cd /d "%~dp0"

where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] uv がインストールされていません。
    echo 次のコマンドでインストールしてください:
    echo   powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
    pause
    exit /b 1
)

if not exist ".venv\Scripts\pythonw.exe" (
    echo [INFO] 初回の準備をしています（数分かかることがあります）...
    uv venv
    if errorlevel 1 goto :error
    uv pip install -e .
    if errorlevel 1 goto :error
)

REM コンソール画面を出さずに起動する
start "" ".venv\Scripts\pythonw.exe" "%~dp0main.py"
exit /b 0

:error
echo [ERROR] 準備に失敗しました。上のメッセージを確認してください。
pause
exit /b 1
