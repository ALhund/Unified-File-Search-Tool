"""テーマ（配色・フォント・スタイルシート）

Windows 11 の Fluent デザインに倣った、ライト/ダーク両対応のテーマ。
色はすべてここで定義したトークンから組み立て、ウィジェット側では
色を直接書かない（テーマ切り替え時に一括で反映できるようにする）。
"""

import sys
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

DEFAULT_ACCENT = "#2F6FEB"

# Windows 向けのフォント（無い場合は順に代替）
UI_FONT_FAMILIES = [
    "Segoe UI Variable Text",
    "Segoe UI",
    "Yu Gothic UI",
    "Meiryo UI",
    "Hiragino Sans",
    "Noto Sans CJK JP",
    "sans-serif",
]
UI_FONT_POINT_SIZE = 10


@dataclass(frozen=True)
class Palette:
    """色のトークン"""
    dark: bool
    window: str  # ウィンドウの地
    surface: str  # パネル・カード
    surface_alt: str  # 入力欄・一段沈んだ面
    border: str
    border_strong: str
    text: str
    text_secondary: str
    text_tertiary: str
    hover: str
    pressed: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_text: str  # アクセント色の上に載せる文字
    accent_soft: str  # 選択行などの淡いアクセント
    accent_fg: str  # 地の上に置くアクセント色の文字・アイコン
    match_bg: str  # 検索語のマーキング
    match_text: str
    warning_bg: str
    warning_border: str
    warning_text: str
    danger: str
    success: str
    preview_bg: str  # プレビュー領域（ページの背景）
    scrollbar: str
    scrollbar_hover: str
    shadow: str


def _mix(a: str, b: str, ratio: float) -> str:
    """色 a と b を ratio（0〜1, b の割合）で混ぜる"""
    ca, cb = QColor(a), QColor(b)
    return QColor(
        round(ca.red() + (cb.red() - ca.red()) * ratio),
        round(ca.green() + (cb.green() - ca.green()) * ratio),
        round(ca.blue() + (cb.blue() - ca.blue()) * ratio),
    ).name()


def _luminance(color: str) -> float:
    c = QColor(color)
    
    def channel(v: int) -> float:
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    
    return 0.2126 * channel(c.red()) + 0.7152 * channel(c.green()) + 0.0722 * channel(c.blue())


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def adjust_accent(accent: str, dark: bool) -> str:
    """アクセント色を背景に対して読みやすい明るさに調整する
    
    Windows のアクセント色は利用者が自由に選べるため（黄色など）、
    そのまま使うと文字やアイコンが見えにくくなることがある。
    """
    color = QColor(accent)
    if not color.isValid():
        color = QColor(DEFAULT_ACCENT)
    h, s, l, _ = color.getHslF()
    h = max(h, 0.0)
    background = "#202022" if dark else "#FFFFFF"
    for _ in range(40):
        candidate = QColor.fromHslF(h, min(s, 0.9), l).name()
        if _contrast(candidate, background) >= 4.0:
            return candidate
        l = l + 0.025 if dark else l - 0.025
        if not 0.05 <= l <= 0.95:
            break
    return QColor.fromHslF(h, min(s, 0.9), max(0.05, min(0.95, l))).name()


def build_palette(dark: bool, accent: str = DEFAULT_ACCENT) -> Palette:
    accent = adjust_accent(accent, dark)
    accent_text = "#FFFFFF" if _contrast(accent, "#FFFFFF") >= _contrast(accent, "#111111") else "#111111"
    
    if dark:
        base = Palette(
            dark=True,
            window="#1C1C1E",
            surface="#262628",
            surface_alt="#2E2E31",
            border="#38383D",
            border_strong="#4C4C53",
            text="#F3F3F5",
            text_secondary="#B0B3BA",
            text_tertiary="#80848C",
            hover="#323236",
            pressed="#3B3B40",
            accent=accent,
            accent_hover=_mix(accent, "#FFFFFF", 0.12),
            accent_pressed=_mix(accent, "#000000", 0.15),
            accent_text=accent_text,
            accent_soft=_mix("#262628", accent, 0.22),
            accent_fg=accent,
            match_bg="#F5C518",
            match_text="#1A1A1A",
            warning_bg="#3B3420",
            warning_border="#6B5A26",
            warning_text="#F1DCA0",
            danger="#FF7B72",
            success="#5FD38D",
            preview_bg="#151517",
            scrollbar="#55555C",
            scrollbar_hover="#74747C",
            shadow="rgba(0, 0, 0, 0.55)",
        )
    else:
        base = Palette(
            dark=False,
            window="#F3F4F6",
            surface="#FFFFFF",
            surface_alt="#F7F8FA",
            border="#E2E4E8",
            border_strong="#C9CDD3",
            text="#1A1C20",
            text_secondary="#5B616B",
            text_tertiary="#8B919A",
            hover="#EEF0F3",
            pressed="#E4E7EB",
            accent=accent,
            accent_hover=_mix(accent, "#FFFFFF", 0.1),
            accent_pressed=_mix(accent, "#000000", 0.12),
            accent_text=accent_text,
            accent_soft=_mix("#FFFFFF", accent, 0.13),
            accent_fg=accent,
            match_bg="#FFE34D",
            match_text="#1A1C20",
            warning_bg="#FFF6D6",
            warning_border="#F0D78A",
            warning_text="#5C4500",
            danger="#C42B1C",
            success="#0F7B3F",
            preview_bg="#E4E6EA",
            scrollbar="#C2C6CC",
            scrollbar_hover="#9EA3AA",
            shadow="rgba(0, 0, 0, 0.18)",
        )
    return base


def system_prefers_dark() -> bool:
    hints = QGuiApplication.styleHints()
    try:
        return hints.colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:
        return QGuiApplication.palette().color(QPalette.ColorRole.Window).lightness() < 128


def system_accent() -> Optional[str]:
    """Windows のアクセント色（取得できなければ None）"""
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as key:
                value, _ = winreg.QueryValueEx(key, "AccentColor")
            # ABGR 形式
            return QColor(value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF).name()
        except OSError:
            pass
    try:
        color = QGuiApplication.palette().color(QPalette.ColorRole.Accent)
        if color.isValid() and sys.platform == "win32":
            return color.name()
    except AttributeError:
        pass
    return None


def ui_font(point_size: float = UI_FONT_POINT_SIZE, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont()
    font.setFamilies(UI_FONT_FAMILIES)
    font.setPointSizeF(point_size)
    font.setWeight(weight)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


# ---------------------------------------------------------------------------
# スタイルシート
# ---------------------------------------------------------------------------

_QSS = """
* {{
    outline: none;
}}
QWidget {{
    color: {text};
    selection-background-color: {accent};
    selection-color: {accent_text};
}}
QMainWindow, QDialog, #AppRoot {{
    background: {window};
}}
QToolTip {{
    background: {surface};
    color: {text};
    border: 1px solid {border_strong};
    border-radius: 6px;
    padding: 5px 8px;
}}

/* ---------- カード（パネル） ---------- */
#Card {{
    background: {surface};
    border: 1px solid {border};
    border-radius: 10px;
}}
#AppBar {{
    background: {surface};
    border-bottom: 1px solid {border};
}}
#AppTitle {{
    font-size: 15px;
    font-weight: 600;
}}
#AppSubtitle, #Secondary {{
    color: {text_secondary};
}}
#Tertiary {{
    color: {text_tertiary};
}}
#SectionTitle {{
    font-weight: 600;
    font-size: 13px;
}}
#PreviewTitle {{
    font-weight: 600;
    font-size: 14px;
}}
#Divider {{
    background: {border};
    max-width: 1px;
    min-width: 1px;
}}
#HDivider {{
    background: {border};
    max-height: 1px;
    min-height: 1px;
}}

/* ---------- 入力欄 ---------- */
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{
    background: {surface_alt};
    border: 1px solid {border};
    border-bottom: 1px solid {border_strong};
    border-radius: 6px;
    padding: 5px 9px;
    min-height: 20px;
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{
    background: {hover};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{
    background: {surface};
    border: 1px solid {border};
    border-bottom: 2px solid {accent};
    padding-bottom: 4px;
}}
QLineEdit:disabled, QComboBox:disabled {{
    color: {text_tertiary};
    background: {window};
}}
QLineEdit[readOnly="true"] {{
    background: {window};
}}
#SearchBox {{
    font-size: 15px;
    padding: 8px 12px;
    border-radius: 8px;
    min-height: 22px;
}}
#SearchBox:focus {{
    padding-bottom: 7px;
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox::down-arrow {{
    image: url("{chevron_down}");
    width: 12px;
    height: 12px;
}}
QComboBox QAbstractItemView {{
    background: {surface};
    border: 1px solid {border_strong};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {accent_soft};
    selection-color: {text};
}}
QComboBox QAbstractItemView::item {{
    min-height: 28px;
    padding: 0 8px;
    border-radius: 4px;
}}

/* ---------- ボタン ---------- */
QPushButton, QToolButton {{
    background: {surface};
    border: 1px solid {border};
    border-bottom: 1px solid {border_strong};
    border-radius: 6px;
    padding: 5px 12px;
    min-height: 20px;
}}
QPushButton:hover, QToolButton:hover {{
    background: {hover};
}}
QPushButton:pressed, QToolButton:pressed {{
    background: {pressed};
    color: {text_secondary};
}}
QPushButton:disabled, QToolButton:disabled {{
    color: {text_tertiary};
    background: {window};
    border-color: {border};
}}
QPushButton#Primary {{
    background: {accent};
    color: {accent_text};
    border: 1px solid {accent_pressed};
    font-weight: 600;
    padding: 6px 18px;
}}
QPushButton#Primary:hover {{
    background: {accent_hover};
}}
QPushButton#Primary:pressed {{
    background: {accent_pressed};
}}
QPushButton#Primary:disabled {{
    background: {border};
    color: {text_tertiary};
    border-color: {border};
}}
QPushButton#Danger {{
    color: {danger};
}}
QPushButton::menu-indicator, QToolButton::menu-indicator {{
    image: none;
    width: 0;
}}

/* 枠なしのアイコンボタン */
QToolButton#Ghost {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px;
}}
QToolButton#Ghost:hover {{
    background: {hover};
}}
QToolButton#Ghost:pressed {{
    background: {pressed};
}}
QToolButton#Ghost:checked {{
    background: {accent_soft};
}}
QToolButton#Ghost:disabled {{
    background: transparent;
}}

/* オン/オフを切り替えるチップ */
QToolButton#Chip {{
    background: {surface};
    border: 1px solid {border};
    border-radius: 15px;
    padding: 4px 11px 4px 8px;
    min-height: 20px;
}}
QToolButton#Chip:hover {{
    background: {hover};
    border-color: {border_strong};
}}
QToolButton#Chip:checked {{
    background: {accent_soft};
    border: 1px solid {accent};
    color: {text};
}}
QToolButton#Chip:checked:hover {{
    border: 1px solid {accent_hover};
}}
QToolButton#Chip:disabled {{
    color: {text_tertiary};
    background: {window};
}}

/* 切り替えボタンの組（セグメント） */
#Segmented {{
    background: {surface_alt};
    border: 1px solid {border};
    border-radius: 7px;
}}
#Segmented QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 5px;
    padding: 4px 10px;
    margin: 2px;
}}
#Segmented QToolButton:hover {{
    background: {hover};
}}
#Segmented QToolButton:checked {{
    background: {surface};
    border: 1px solid {border_strong};
    font-weight: 600;
}}
#Segmented QToolButton:disabled {{
    color: {text_tertiary};
}}

/* ---------- 一覧 ---------- */
QListView, QTreeView, QTableView, QTableWidget {{
    background: {surface};
    border: none;
    border-radius: 8px;
    alternate-background-color: {surface_alt};
    gridline-color: {border};
}}
QHeaderView::section {{
    background: {surface_alt};
    border: none;
    border-bottom: 1px solid {border};
    padding: 6px 8px;
    color: {text_secondary};
    font-weight: 600;
}}
QTableWidget::item {{
    padding: 4px 8px;
}}
QTableWidget::item:selected {{
    background: {accent_soft};
    color: {text};
}}

/* ---------- スクロールバー ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 2px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
    margin: 2px;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {scrollbar};
    border-radius: 4px;
    margin: 1px;
}}
QScrollBar::handle:vertical {{ min-height: 32px; }}
QScrollBar::handle:horizontal {{ min-width: 32px; }}
QScrollBar::handle:hover {{
    background: {scrollbar_hover};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

/* ---------- チェックボックス・スライダー ---------- */
QCheckBox, QRadioButton {{
    spacing: 8px;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 18px;
    height: 18px;
}}
QCheckBox::indicator {{
    border: 1px solid {border_strong};
    border-radius: 4px;
    background: {surface_alt};
}}
QCheckBox::indicator:hover {{
    background: {hover};
}}
QCheckBox::indicator:checked {{
    background: {accent};
    border-color: {accent};
    image: url("{check_icon}");
}}
QRadioButton::indicator {{
    border: 1px solid {border_strong};
    border-radius: 9px;
    background: {surface_alt};
}}
QRadioButton::indicator:checked {{
    border: 5px solid {accent};
    background: {accent_text};
}}
QSlider::groove:horizontal {{
    height: 4px;
    background: {border_strong};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {accent};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {surface};
    border: 4px solid {accent};
    width: 10px;
    height: 10px;
    margin: -6px 0;
    border-radius: 9px;
}}
QSlider::handle:horizontal:hover {{
    border-width: 3px;
}}

/* ---------- 進捗バー ---------- */
QProgressBar {{
    background: {border};
    border: none;
    border-radius: 2px;
    max-height: 4px;
    min-height: 4px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: {accent};
    border-radius: 2px;
}}

/* ---------- メニュー ---------- */
QMenu {{
    background: {surface};
    border: 1px solid {border_strong};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 28px 6px 12px;
    border-radius: 4px;
    margin: 1px 0;
}}
QMenu::item:selected {{
    background: {hover};
}}
QMenu::item:disabled {{
    color: {text_tertiary};
}}
QMenu::icon {{
    padding-left: 8px;
}}
QMenu::separator {{
    height: 1px;
    background: {border};
    margin: 4px 6px;
}}

/* ---------- スプリッター・タブ ---------- */
QSplitter::handle {{
    background: transparent;
}}
QSplitter::handle:hover {{
    background: {accent_soft};
}}
QTabWidget::pane {{
    border: 1px solid {border};
    border-radius: 8px;
    background: {surface};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    border: none;
    padding: 7px 14px;
    color: {text_secondary};
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{
    color: {text};
    font-weight: 600;
    border-bottom: 2px solid {accent};
}}
QTabBar::tab:hover {{
    color: {text};
}}

/* ---------- 通知（インフォバー） ---------- */
#InfoBar {{
    background: {warning_bg};
    border: 1px solid {warning_border};
    border-radius: 8px;
}}
#InfoBar QLabel {{
    color: {warning_text};
}}
#Badge {{
    background: {accent_soft};
    color: {accent_fg};
    border-radius: 9px;
    padding: 1px 8px;
    font-weight: 600;
}}
#Kbd {{
    background: {surface_alt};
    border: 1px solid {border_strong};
    border-radius: 4px;
    padding: 0 5px;
    color: {text_secondary};
    font-size: 11px;
}}
#StatusBar {{
    background: {surface};
    border-top: 1px solid {border};
}}
#StatusBar QLabel {{
    color: {text_secondary};
}}
#EmptyTitle {{
    font-size: 16px;
    font-weight: 600;
}}
#EmptyText {{
    color: {text_secondary};
}}
QDialog #DialogTitle {{
    font-size: 18px;
    font-weight: 600;
}}
#SettingsGroup {{
    background: {surface};
    border: 1px solid {border};
    border-radius: 8px;
}}
#SettingsRowTitle {{
    font-weight: 600;
}}
#LicenseBar {{
    background: {accent_soft};
    border-bottom: 1px solid {border};
}}
#LicenseBar[expired="true"] {{
    background: {warning_bg};
    border-bottom: 1px solid {warning_border};
}}
#LicenseNotice {{
    background: {warning_bg};
    border: 1px solid {warning_border};
    border-radius: 8px;
    padding: 8px 10px;
    color: {warning_text};
}}
#ErrorText {{
    color: {danger};
}}
"""


class ThemeManager(QObject):
    """テーマの適用と切り替えを管理する（アプリ全体で1つ）"""
    
    changed = Signal(object)  # Palette
    
    def __init__(self):
        super().__init__()
        self.mode = "system"  # system / light / dark
        self.use_system_accent = True
        self.palette = build_palette(False)
        self._resource_cache: dict[str, str] = {}
    
    def is_dark(self) -> bool:
        if self.mode == "dark":
            return True
        if self.mode == "light":
            return False
        return system_prefers_dark()
    
    def apply(self, app: Optional[QApplication] = None) -> None:
        """現在の設定でテーマを適用する"""
        app = app or QApplication.instance()
        accent = (system_accent() if self.use_system_accent else None) or DEFAULT_ACCENT
        self.palette = build_palette(self.is_dark(), accent)
        p = self.palette
        
        from src.ui import icons
        
        icons.clear_cache()
        
        app.setFont(ui_font())
        
        qt_palette = QPalette()
        roles = {
            QPalette.ColorRole.Window: p.window,
            QPalette.ColorRole.WindowText: p.text,
            QPalette.ColorRole.Base: p.surface,
            QPalette.ColorRole.AlternateBase: p.surface_alt,
            QPalette.ColorRole.Text: p.text,
            QPalette.ColorRole.Button: p.surface,
            QPalette.ColorRole.ButtonText: p.text,
            QPalette.ColorRole.Highlight: p.accent,
            QPalette.ColorRole.HighlightedText: p.accent_text,
            QPalette.ColorRole.ToolTipBase: p.surface,
            QPalette.ColorRole.ToolTipText: p.text,
            QPalette.ColorRole.PlaceholderText: p.text_tertiary,
            QPalette.ColorRole.Link: p.accent_fg,
            QPalette.ColorRole.Mid: p.border,
            QPalette.ColorRole.Midlight: p.surface_alt,
            QPalette.ColorRole.Dark: p.border_strong,
        }
        for role, color in roles.items():
            qt_palette.setColor(role, QColor(color))
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
            qt_palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(p.text_tertiary))
        try:
            qt_palette.setColor(QPalette.ColorRole.Accent, QColor(p.accent))
        except AttributeError:
            pass
        app.setPalette(qt_palette)
        
        tokens = {name: getattr(p, name) for name in p.__dataclass_fields__ if name != "dark"}
        tokens["chevron_down"] = icons.icon_file("chevron-down", p.text_secondary)
        tokens["check_icon"] = icons.icon_file("check", p.accent_text)
        app.setStyleSheet(_QSS.format(**tokens))
        
        self.changed.emit(p)


_manager: Optional[ThemeManager] = None


def theme() -> ThemeManager:
    global _manager
    if _manager is None:
        _manager = ThemeManager()
    return _manager


def palette() -> Palette:
    return theme().palette
