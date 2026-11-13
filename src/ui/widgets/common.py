"""共通の小さな部品"""

from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.ui import icons
from src.ui.theme import theme


def card(parent: Optional[QWidget] = None) -> QFrame:
    frame = QFrame(parent)
    frame.setObjectName("Card")
    return frame


def divider(vertical: bool = True) -> QFrame:
    line = QFrame()
    line.setObjectName("Divider" if vertical else "HDivider")
    if vertical:
        line.setFixedWidth(1)
        line.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        line.setMinimumHeight(20)
    else:
        line.setFixedHeight(1)
    return line


def ghost_button(
    icon_name: str,
    tooltip: str,
    parent: Optional[QWidget] = None,
    checkable: bool = False,
    size: int = 18,
    role: str = "text",
) -> QToolButton:
    """枠なしのアイコンボタン"""
    button = QToolButton(parent)
    button.setObjectName("Ghost")
    button.setToolTip(tooltip)
    button.setCheckable(checkable)
    button.setAutoRaise(True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFixedSize(QSize(size + 14, size + 14))
    icons.bind(button, icon_name, role, size)
    return button


def chip(text: str, icon_name: Optional[str] = None, tooltip: str = "", checkable: bool = True) -> QToolButton:
    """オン/オフを切り替える丸いボタン"""
    button = QToolButton()
    button.setObjectName("Chip")
    button.setText(text)
    button.setToolTip(tooltip)
    button.setCheckable(checkable)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    if icon_name:
        icons.bind(button, icon_name, "secondary", 16)
    return button


def primary_button(text: str, icon_name: Optional[str] = None) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("Primary")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if icon_name:
        icons.bind(button, icon_name, "on_accent", 16)
    return button


def label(text: str = "", object_name: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if object_name:
        widget.setObjectName(object_name)
    widget.setWordWrap(wrap)
    return widget


class ElidedLabel(QLabel):
    """幅に収まらない文字を「…」で省略して表示するラベル"""
    
    def __init__(self, text: str = "", mode: Qt.TextElideMode = Qt.TextElideMode.ElideMiddle, parent=None):
        super().__init__(parent)
        self._full = text
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(40)
        self.setText(text)
    
    def setText(self, text: str) -> None:  # noqa: N802 (Qtの命名に合わせる)
        self._full = text
        self.setToolTip(text)
        self._update()
    
    def full_text(self) -> str:
        return self._full
    
    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._update()
    
    def _update(self) -> None:
        metrics = QFontMetrics(self.font())
        super().setText(metrics.elidedText(self._full, self._mode, max(10, self.width())))


class Segmented(QFrame):
    """いずれか1つを選ぶ切り替えボタンの組"""
    
    changed = Signal(str)
    
    def __init__(self, items: list[tuple[str, str, Optional[str], str]], parent=None):
        """items: (値, 表示名, アイコン名, ツールチップ)"""
        super().__init__(parent)
        self.setObjectName("Segmented")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QToolButton] = {}
        for value, text, icon_name, tooltip in items:
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tooltip)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            if icon_name:
                icons.bind(button, icon_name, "secondary", 16)
            button.clicked.connect(lambda _=False, v=value: self.changed.emit(v))
            self._group.addButton(button)
            self._buttons[value] = button
            layout.addWidget(button)
    
    def value(self) -> Optional[str]:
        for value, button in self._buttons.items():
            if button.isChecked():
                return value
        return None
    
    def set_value(self, value: str) -> None:
        if value in self._buttons:
            self._buttons[value].setChecked(True)
    
    def set_item_enabled(self, value: str, enabled: bool) -> None:
        if value in self._buttons:
            self._buttons[value].setEnabled(enabled)
    
    def button(self, value: str) -> Optional[QToolButton]:
        return self._buttons.get(value)


class InfoBar(QFrame):
    """補足・注意のメッセージ（閉じるボタンつき）"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("InfoBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 6, 6)
        layout.setSpacing(8)
        self._icon = QLabel()
        self._icon.setFixedSize(18, 18)
        layout.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        self._text = QLabel()
        self._text.setWordWrap(True)
        self._text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._text, 1)
        close = ghost_button("close", "閉じる", size=14, role="warning")
        close.clicked.connect(self.hide)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        theme().changed.connect(lambda _: self._update_icon())
        self._update_icon()
        self.hide()
    
    def _update_icon(self) -> None:
        self._icon.setPixmap(icons.pixmap("info", theme().palette.warning_text, 18))
    
    def show_message(self, text: str) -> None:
        self._text.setText(text)
        self.setVisible(bool(text))


class EmptyState(QWidget):
    """何も表示するものがないときの案内"""
    
    action_clicked = Signal()
    
    def __init__(self, icon_name: str, title: str, text: str = "", action: str = "", parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)
        layout.addStretch(1)
        
        self._icon = QLabel()
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon)
        
        self._title = label(title, "EmptyTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setWordWrap(True)
        layout.addWidget(self._title)
        
        self._text = label(text, "EmptyText", wrap=True)
        self._text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self._text)
        
        self._action = QPushButton(action)
        self._action.setCursor(Qt.CursorShape.PointingHandCursor)
        self._action.clicked.connect(self.action_clicked.emit)
        self._action.setVisible(bool(action))
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._action)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(2)
        
        theme().changed.connect(lambda _: self._update_icon())
        self._update_icon()
    
    def _update_icon(self) -> None:
        p = theme().palette
        self._icon.setPixmap(icons.pixmap(self._icon_name, p.text_tertiary, 56))
    
    def set_content(self, icon_name: str, title: str, text: str = "", action: str = "") -> None:
        self._icon_name = icon_name
        self._title.setText(title)
        self._text.setText(text)
        self._text.setVisible(bool(text))
        self._action.setText(action)
        self._action.setVisible(bool(action))
        self._update_icon()
