@echo off
REM Unified File Search Tool 起動バッチ
REM uvを使用して仮想環境を作成・起動

cd /d "%~dp0"

REM uvがインストールされているか確認
where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] uvがインストールされていません。
    echo 以下のコマンドでインストールしてください:
    echo   powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
    pause
    exit /b 1
)

REM 初回は依存関係をインストール
if not exist ".venv" (
    echo [INFO] 仮想環境を作成中...
    uv venv
    echo [INFO] 依存関係をインストール中...
    uv pip install -e .
)

REM アプリケーション起動
echo [INFO] アプリケーションを起動中...
uv run python main.py

pause
