"""OS（主に Windows）との連携"""

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QDesktopServices

APP_USER_MODEL_ID = "UnifiedFileSearchTool.App"

# DwmSetWindowAttribute の属性
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWA_CAPTION_COLOR = 35
_DWMWA_TEXT_COLOR = 36
_DWMWCP_ROUND = 2


def set_app_user_model_id() -> None:
    """タスクバーで python.exe ではなく本アプリのアイコンを表示させる"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


def style_title_bar(window, dark: bool, caption: str, text: str) -> None:
    """Windows 10/11 のタイトルバーをアプリの配色に合わせる（未対応のOSでは何もしない）"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        
        hwnd = wintypes.HWND(int(window.winId()))
        dwm = ctypes.windll.dwmapi
        
        def set_attr(attribute: int, value: int) -> None:
            data = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data))
        
        def colorref(color: str) -> int:
            c = QColor(color)
            return c.red() | (c.green() << 8) | (c.blue() << 16)
        
        set_attr(_DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0)
        set_attr(_DWMWA_WINDOW_CORNER_PREFERENCE, _DWMWCP_ROUND)
        # 以下は Windows 11 のみ有効（10 では無視される）
        set_attr(_DWMWA_CAPTION_COLOR, colorref(caption))
        set_attr(_DWMWA_TEXT_COLOR, colorref(text))
    except Exception:
        pass


def open_file(path: Path) -> None:
    """既定のアプリで開く"""
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def reveal_in_explorer(path: Path) -> None:
    """エクスプローラーでファイルを選択した状態で開く"""
    path = Path(path)
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
            return
    except OSError:
        pass
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent if path.is_file() else path)))


def file_manager_name() -> str:
    if sys.platform == "win32":
        return "エクスプローラー"
    if sys.platform == "darwin":
        return "Finder"
    return "ファイルマネージャー"
