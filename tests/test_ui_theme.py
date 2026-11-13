"""テーマ・アイコンのテスト（画面は表示しない）"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_accent_is_adjusted_for_contrast():
    from src.ui.theme import _contrast, adjust_accent
    
    # 黄色のアクセントでも、白地・黒地の上で読める濃さになる
    assert _contrast(adjust_accent("#FFD800", dark=False), "#FFFFFF") >= 4.0
    assert _contrast(adjust_accent("#0A1A6A", dark=True), "#202022") >= 4.0


@pytest.mark.parametrize("dark", [False, True])
def test_theme_applies_stylesheet(app, dark):
    from src.ui.theme import theme
    
    manager = theme()
    manager.mode = "dark" if dark else "light"
    manager.use_system_accent = False
    manager.apply(app)
    assert manager.palette.dark is dark
    assert "#Card" in app.styleSheet()
    assert "{" in app.styleSheet() and "{{" not in app.styleSheet()


def test_all_icons_render(app):
    from src.ui import icons
    
    for name in icons._ICONS:
        pixmap = icons.pixmap(name, "#000000", 24)
        assert not pixmap.isNull(), name
    for extension in list(icons.FILE_TYPES) + ["unknown"]:
        assert not icons.file_pixmap(extension, 32).isNull()
    assert not icons.app_icon().isNull()


def test_user_settings_round_trip(tmp_path):
    from PySide6.QtCore import QSettings
    from src.ui.settings import MAX_HISTORY, UserSettings
    
    settings = UserSettings(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    for i in range(MAX_HISTORY + 5):
        settings.add_query(f"q{i}")
    settings.add_query("q3")
    history = settings.query_history
    assert history[0] == "q3" and len(history) == MAX_HISTORY and history.count("q3") == 1
    settings.match_limit = 0
    assert settings.match_limit == 0
