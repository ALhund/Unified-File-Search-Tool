"""ステータスバー（画面下）"""

from typing import Optional

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QWidget

from src.ui import icons
from src.ui.theme import theme


class StatusBar(QFrame):
    """状態・進捗・処理時間の表示"""
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("StatusBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 5, 14, 6)
        layout.setSpacing(10)
        
        self._icon = QLabel()
        self._icon.setFixedSize(16, 16)
        layout.addWidget(self._icon)
        self._icon_name = "info"
        
        self._message = QLabel("準備完了")
        layout.addWidget(self._message, 1)
        
        self._progress_text = QLabel("")
        self._progress_text.hide()
        layout.addWidget(self._progress_text)
        
        self._progress = QProgressBar()
        self._progress.setFixedWidth(180)
        self._progress.setTextVisible(False)
        self._progress.hide()
        layout.addWidget(self._progress)
        
        self._time = QLabel("")
        layout.addWidget(self._time)
        
        self._index = QLabel("")
        self._index.setToolTip("常時インデックスの状態（設定で対象フォルダを変更できます）")
        layout.addWidget(self._index)
        
        self._engine = QLabel("")
        layout.addWidget(self._engine)
        
        theme().changed.connect(lambda _: self._update_icon())
        self._update_icon()
    
    def _update_icon(self) -> None:
        p = theme().palette
        color = {"warning": p.danger, "check": p.success}.get(self._icon_name, p.text_secondary)
        self._icon.setPixmap(icons.pixmap(self._icon_name, color, 16))
    
    def set_message(self, message: str, icon_name: str = "info") -> None:
        self._message.setText(message)
        self._icon_name = icon_name
        self._update_icon()
    
    def set_index(self, text: str) -> None:
        self._index.setText(text)
    
    def set_engine(self, text: str) -> None:
        self._engine.setText(text)
    
    def show_progress(self, visible: bool) -> None:
        self._progress.setVisible(visible)
        self._progress_text.setVisible(visible)
        if not visible:
            self._progress.setRange(0, 100)
            self._progress.setValue(0)
            self._progress_text.setText("")
    
    def set_progress(self, value: int, maximum: int, text: str = "") -> None:
        self._progress.setRange(0, maximum)
        self._progress.setValue(value)
        self._progress_text.setText(text)
    
    def set_indeterminate(self) -> None:
        self._progress.setRange(0, 0)
    
    def set_time(self, seconds: float) -> None:
        if seconds < 1:
            text = f"{seconds * 1000:.0f} ms"
        elif seconds < 60:
            text = f"{seconds:.1f} 秒"
        else:
            text = f"{int(seconds // 60)} 分 {seconds % 60:.0f} 秒"
        self._time.setText(f"処理時間 {text}")
    
    def clear_time(self) -> None:
        self._time.setText("")
