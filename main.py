"""Unified File Search Tool - エントリーポイント"""

import multiprocessing
import sys
from pathlib import Path

# srcをパスに追加
sys.path.insert(0, str(Path(__file__).parent))


def main() -> int:
    """メイン関数"""
    # Qt関連は main() の中で読み込む。
    # 検索用のワーカープロセスはこのファイルを再読み込みするため、
    # トップレベルで読み込むとワーカーごとにQtを起動してしまう。
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    
    from src.common.config import get_config
    from src.common.logger import get_logger
    from src.preview.scheme import register_scheme
    
    # プレビュー用URLスキームは QApplication より前に登録する必要がある
    register_scheme()
    
    # 高DPI対応
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)
    app.setApplicationName("Unified File Search Tool")
    app.setApplicationVersion("0.2.0")
    app.setStyle("Fusion")
    
    get_config()
    logger = get_logger("main")
    logger.info("application_starting", "Application starting")
    
    from src.ui import MainWindow
    
    window = MainWindow()
    window.show()
    
    exit_code = app.exec()
    
    logger.info("application_exiting", "Application exiting", exit_code=exit_code)
    return exit_code


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
