#!/bin/bash
# Unified File Search 起動スクリプト (Linux/Mac用)

cd "$(dirname "$0")"

if ! command -v uv &> /dev/null; then
    echo "[ERROR] uv がインストールされていません。"
    echo "次のコマンドでインストールしてください:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "[INFO] 初回の準備をしています..."
    uv venv
    uv pip install -e .
fi

echo "[INFO] アプリケーションを起動中..."
uv run python main.py
