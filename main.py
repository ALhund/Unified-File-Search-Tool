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
    from src.ui.platform import set_app_user_model_id
    
    # タスクバーに python.exe ではなく本アプリのアイコンを出す
    set_app_user_model_id()
    # プレビュー用URLスキームは QApplication より前に登録する必要がある
    register_scheme()
    
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)
    app.setApplicationName("Unified File Search")
    app.setApplicationDisplayName("Unified File Search")
    app.setOrganizationName("UnifiedFileSearchTool")
    app.setApplicationVersion("0.3.0")
    app.setStyle("Fusion")
    
    from src.ui import icons
    from src.ui.settings import UserSettings, apply_to_config
    from src.ui.theme import theme
    
    app.setWindowIcon(icons.app_icon())
    
    get_config()
    settings = UserSettings()
    apply_to_config(settings)
    
    manager = theme()
    manager.mode = settings.theme
    manager.use_system_accent = settings.use_system_accent
    manager.apply(app)
    
    logger = get_logger("main")
    logger.info("application_starting", "Application starting")
    
    from src.ui import MainWindow
    
    window = MainWindow(settings)
    window.show()
    
    exit_code = app.exec()
    
    logger.info("application_exiting", "Application exiting", exit_code=exit_code)
    return exit_code


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
