"""ライセンスの登録画面と、体験版の案内バー"""

import re
from typing import Optional

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from src.licensing import LicenseError, LicenseManager, LicenseState
from src.licensing import policy
from src.ui import icons
from src.ui.theme import theme
from src.ui.widgets.common import label, primary_button

_CODE_RE = re.compile(r"UFS1[-\sA-Za-z0-9]{100,}", re.IGNORECASE)
# 行頭の「登録名:」の後（同じ行か次の行）にある名前
_NAME_RE = re.compile(r"^[ \t]*登録名[ \t]*[:：][ \t]*(?:\r?\n[ \t]*)?(\S.*?)[ \t]*$", re.MULTILINE)


def parse_pasted(text: str) -> tuple[str, str]:
    """購入時のメッセージをまるごと貼り付けたときに、登録名とコードを取り出す"""
    name = ""
    code = ""
    if match := _CODE_RE.search(text):
        code = match.group(0).strip()
    if match := _NAME_RE.search(text):
        candidate = match.group(1).strip()
        if candidate and not candidate.upper().startswith("UFS1"):
            name = candidate
    return name, code


class LicenseDialog(QDialog):
    """ライセンスの登録・確認"""
    
    def __init__(self, manager: LicenseManager, parent=None, reason: str = ""):
        super().__init__(parent)
        self._manager = manager
        self.setWindowTitle("ライセンスの登録")
        self.setMinimumWidth(560)
        self.changed = False
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 20)
        layout.setSpacing(10)
        
        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(icons.app_icon().pixmap(40, 40))
        head.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(label("ライセンスの登録", "DialogTitle"))
        self._state_label = label("", "Secondary")
        titles.addWidget(self._state_label)
        head.addLayout(titles, 1)
        layout.addLayout(head)
        
        if reason:
            notice = label(reason, "", wrap=True)
            notice.setObjectName("LicenseNotice")
            layout.addWidget(notice)
        
        # --- 登録済みの表示 ---
        self._licensed_box = QFrame()
        self._licensed_box.setObjectName("SettingsGroup")
        licensed_layout = QVBoxLayout(self._licensed_box)
        licensed_layout.setContentsMargins(16, 12, 16, 12)
        self._licensed_text = label("", "", wrap=True)
        self._licensed_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        licensed_layout.addWidget(self._licensed_text)
        release = QPushButton("このパソコンの登録を解除")
        release.setObjectName("Danger")
        release.clicked.connect(self._deactivate)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(release)
        licensed_layout.addLayout(row)
        layout.addWidget(self._licensed_box)
        
        # --- 入力欄 ---
        self._form = QFrame()
        form = QVBoxLayout(self._form)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)
        form.addWidget(label(
            "購入時にお送りした「登録名」と「ライセンスコード」を入力してください。"
            "お知らせした文面をまるごとコピーして「貼り付け」を押すと、両方まとめて入力されます。",
            "Secondary", wrap=True,
        ))
        paste = QPushButton("クリップボードから貼り付け")
        icons.bind(paste, "copy", "text", 16)
        paste.clicked.connect(self._paste)
        row = QHBoxLayout()
        row.addWidget(paste)
        row.addStretch(1)
        form.addLayout(row)
        form.addWidget(label("登録名", "SettingsRowTitle"))
        self._name = QLineEdit()
        self._name.setPlaceholderText("例: 山田 太郎")
        form.addWidget(self._name)
        form.addWidget(label("ライセンスコード", "SettingsRowTitle"))
        self._code = QPlainTextEdit()
        self._code.setPlaceholderText("UFS1-XXXXXX-XXXXXX-…")
        self._code.setFixedHeight(84)
        form.addWidget(self._code)
        self._error = label("", "", wrap=True)
        self._error.setObjectName("ErrorText")
        self._error.hide()
        form.addWidget(self._error)
        layout.addWidget(self._form)
        
        if policy.SUPPORT_TEXT:
            layout.addWidget(label(policy.SUPPORT_TEXT, "Tertiary", wrap=True))
        
        # --- ボタン ---
        buttons = QHBoxLayout()
        if policy.PURCHASE_URL:
            buy = QPushButton("購入ページを開く")
            icons.bind(buy, "external", "text", 16)
            buy.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(policy.PURCHASE_URL)))
            buttons.addWidget(buy)
        buttons.addStretch(1)
        self._close = QPushButton("閉じる")
        self._close.clicked.connect(self.reject)
        buttons.addWidget(self._close)
        self._register = primary_button("登録する")
        self._register.clicked.connect(self._activate)
        self._register.setDefault(True)
        buttons.addWidget(self._register)
        layout.addLayout(buttons)
        
        self._refresh()
    
    def _refresh(self) -> None:
        state = self._manager.state()
        self._state_label.setText(state.summary())
        licensed = state.status == "licensed"
        self._licensed_box.setVisible(licensed)
        self._form.setVisible(not licensed)
        self._register.setVisible(not licensed)
        if licensed and state.info:
            info = state.info
            self._licensed_text.setText(
                f"<b>{info.name} 様</b><br>{state.edition_name}　ライセンス番号 {info.license_id}"
                f"　発行日 {info.issued:%Y/%m/%d}<br><br>ご購入ありがとうございます。すべての機能をお使いいただけます。"
            )
    
    def _paste(self) -> None:
        text = QGuiApplication.clipboard().text()
        name, code = parse_pasted(text)
        if code:
            self._code.setPlainText(code)
        if name:
            self._name.setText(name)
        if not code and not name and text.strip():
            self._code.setPlainText(text.strip())
    
    def _activate(self) -> None:
        try:
            info = self._manager.activate(self._name.text(), self._code.toPlainText())
        except LicenseError as e:
            self._error.setText(str(e))
            self._error.show()
            return
        self.changed = True
        self._error.hide()
        QMessageBox.information(self, "ライセンスの登録", f"{info.name} 様、ご登録ありがとうございます。\nすべての機能をお使いいただけます。")
        self.accept()
    
    def _deactivate(self) -> None:
        answer = QMessageBox.question(
            self, "登録の解除",
            "このパソコンのライセンス登録を解除します。別のパソコンで使う場合などに解除してください。\n"
            "（登録名とライセンスコードがあれば、いつでも登録し直せます）",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._manager.deactivate()
            self.changed = True
            self._refresh()


class LicenseBar(QFrame):
    """体験版の残り日数・期限切れの案内（画面上部の帯）"""
    
    register_requested = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LicenseBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 7, 12, 7)
        layout.setSpacing(10)
        self._icon = QLabel()
        layout.addWidget(self._icon)
        self._text = QLabel()
        layout.addWidget(self._text, 1)
        if policy.PURCHASE_URL:
            buy = QPushButton("購入ページ")
            buy.setCursor(Qt.CursorShape.PointingHandCursor)
            buy.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(policy.PURCHASE_URL)))
            layout.addWidget(buy)
        self._button = primary_button("ライセンスを登録")
        self._button.clicked.connect(self.register_requested.emit)
        layout.addWidget(self._button)
        self._expired = False
        theme().changed.connect(lambda _: self._update_icon())
        self.hide()
    
    def _update_icon(self) -> None:
        p = theme().palette
        self._icon.setPixmap(icons.pixmap("warning" if self._expired else "info",
                                          p.danger if self._expired else p.accent_fg, 18))
    
    def set_state(self, state: Optional[LicenseState]) -> None:
        if state is None or state.status in ("licensed", "unconfigured"):
            self.hide()
            return
        self._expired = state.status == "expired"
        if self._expired:
            self._text.setText("体験期間が終了しました。引き続き検索するには、ライセンスを登録してください。")
        else:
            self._text.setText(
                f"体験版をお使いです（残り <b>{state.trial_days_left} 日</b>）。期間中はすべての機能をお使いいただけます。"
            )
        self.setProperty("expired", self._expired)
        self.style().unpolish(self)
        self.style().polish(self)
        self._update_icon()
        self.show()
