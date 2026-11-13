"""アプリのファイルの場所

- 開発時: リポジトリのフォルダ
- 実行ファイル（PyInstaller）: 同梱リソースは sys._MEIPASS（_internal）、
  利用者が触るファイル（Config・licenses）は実行ファイルと同じフォルダ
"""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """アイコンなど、アプリに同梱したリソースの置き場所"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return _PROJECT_ROOT


def app_dir() -> Path:
    """実行ファイル（開発時はリポジトリ）のフォルダ"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return _PROJECT_ROOT
