"""Unified File Search Tool - エントリーポイント"""

import sys
from pathlib import Path

# srcをパスに追加
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from src.ui import MainWindow
from src.common.config import get_config
from src.common.logger import get_logger


def main():
    """メイン関数"""
    # 高DPI対応
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    # アプリケーション作成
    app = QApplication(sys.argv)
    app.setApplicationName("Unified File Search Tool")
    app.setApplicationVersion("1.0.0")
    
    # スタイル設定
    app.setStyle("Fusion")
    
    # 設定とロガーを初期化
    config = get_config()
    logger = get_logger("main")
    
    logger.info("application_starting")
    
    # メインウィンドウ作成
    window = MainWindow()
    window.show()
    
    # イベントループ
    exit_code = app.exec()
    
    logger.info("application_exiting", exit_code=exit_code)
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
