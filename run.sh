#!/bin/bash
# Unified File Search Tool 起動スクリプト (Linux/Mac用)

cd "$(dirname "$0")"

# uvがインストールされているか確認
if ! command -v uv &> /dev/null; then
    echo "[ERROR] uvがインストールされていません。"
    echo "以下のコマンドでインストールしてください:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# 初回は依存関係をインストール
if [ ! -d ".venv" ]; then
    echo "[INFO] 仮想環境を作成中..."
    uv venv
    echo "[INFO] 依存関係をインストール中..."
    uv pip install -e .
fi

# アプリケーション起動
echo "[INFO] アプリケーションを起動中..."
uv run python main.py
