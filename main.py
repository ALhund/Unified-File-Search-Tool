"""Unified File Search - エントリーポイント"""

import multiprocessing
import os
import sys
import time
from pathlib import Path

_STARTED = time.perf_counter()

# srcをパスに追加
sys.path.insert(0, str(Path(__file__).parent))


def main() -> int:
    """メイン関数"""
    # Qt関連は main() の中で読み込む。
    # 検索用のワーカープロセスはこのファイルを再読み込みするため、
    # トップレベルで読み込むとワーカーごとにQtを起動してしまう。
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    
    from src import APP_NAME, __version__
    from src.common.config import get_config
    from src.common.logger import get_logger
    from src.ui.platform import set_app_user_model_id
    
    # タスクバーに python.exe ではなく本アプリのアイコンを出す
    set_app_user_model_id()
    
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("UnifiedFileSearchTool")
    app.setApplicationVersion(__version__)
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
    logger.info("application_starting", "Application starting", version=__version__)
    
    from src.ui import MainWindow
    
    window = MainWindow(settings)
    window.show()
    
    def startup_done() -> None:
        # 起動にかかった時間を記録する（遅いと言われたときの調査用）
        elapsed_ms = int((time.perf_counter() - _STARTED) * 1000)
        logger.info("startup", "Window shown", elapsed_ms=elapsed_ms)
        if mark := os.environ.get("UFST_STARTUP_MARK"):
            Path(mark).write_text(str(elapsed_ms), encoding="utf-8")
    
    from PySide6.QtCore import QTimer
    QTimer.singleShot(0, startup_done)
    
    exit_code = app.exec()
    
    logger.info("application_exiting", "Application exiting", exit_code=exit_code)
    return exit_code


def dispatch(argv: list[str]) -> int:
    """起動モードの振り分け（実行ファイルから補助的な処理を呼ぶために使う）"""
    if len(argv) >= 2 and argv[1] == "--convert-with-msoffice":
        # Microsoft Office での変換（converter.py が別プロセスとして呼ぶ）
        from src.preview import msoffice_convert
        return msoffice_convert.main([argv[0]] + argv[2:])
    if len(argv) >= 2 and argv[1] == "--self-test":
        from src.selftest import run
        report = Path(argv[2]) if len(argv) >= 3 else Path("selftest.json")
        return run(report)
    return main()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(dispatch(sys.argv))
