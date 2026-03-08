"""Unified File Search Tool - エントリーポイント。

アプリケーションの初期化、QApplication の設定、
メインウィンドウの起動を行う。
"""

import sys
from pathlib import Path

# src をパスに追加（パッケージを直接実行する場合の互換性確保）
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.common.config import get_config
from src.common.logger import get_logger
from src.ui import MainWindow


def main() -> int:
    """アプリケーションのエントリーポイント。

    高 DPI スケーリング設定、QApplication 生成、Fusion スタイルの適用、
    メインウィンドウの表示、Qt イベントループの実行を順に行う。

    Returns:
        Qt イベントループの終了コード（正常終了は 0）。
    """
    # 高 DPI スケーリング設定
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Unified File Search Tool")
    app.setApplicationVersion("1.0.0")
    app.setStyle("Fusion")

    # 設定・ロガーを初期化
    get_config()
    logger = get_logger("main")
    logger.info("application_starting", "Application starting")

    window = MainWindow()
    window.show()

    exit_code = app.exec()

    logger.info("application_exiting", "Application exiting", exit_code=exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
