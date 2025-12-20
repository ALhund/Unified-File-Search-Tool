"""ステータスバー"""

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QLabel,
    QProgressBar,
)


class StatusBar(QWidget):
    """ステータスバー"""
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        """UIを構築"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(16)
        
        # ステータスメッセージ
        self._message_label = QLabel("準備完了")
        layout.addWidget(self._message_label)
        
        layout.addStretch()
        
        # プログレスバー
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedWidth(200)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.hide()
        layout.addWidget(self._progress_bar)
        
        # 進捗情報
        self._progress_label = QLabel("")
        self._progress_label.hide()
        layout.addWidget(self._progress_label)
        
        # 処理時間
        self._time_label = QLabel("")
        layout.addWidget(self._time_label)
    
    def set_message(self, message: str):
        """メッセージを設定"""
        self._message_label.setText(message)
    
    def show_progress(self, visible: bool = True):
        """プログレスバーの表示/非表示"""
        self._progress_bar.setVisible(visible)
        self._progress_label.setVisible(visible)
        if not visible:
            self._progress_bar.setValue(0)
            self._progress_label.setText("")
    
    def set_progress(
        self,
        value: int,
        maximum: int = 100,
        text: Optional[str] = None,
    ):
        """進捗を設定
        
        Args:
            value: 現在値
            maximum: 最大値
            text: 進捗テキスト（例: "10/100 ファイル処理中"）
        """
        self._progress_bar.setMaximum(maximum)
        self._progress_bar.setValue(value)
        
        if text:
            self._progress_label.setText(text)
    
    def set_indeterminate(self, indeterminate: bool = True):
        """不定進捗モードを設定"""
        if indeterminate:
            self._progress_bar.setRange(0, 0)
        else:
            self._progress_bar.setRange(0, 100)
    
    def set_time(self, seconds: float):
        """処理時間を設定"""
        if seconds < 1:
            text = f"{seconds*1000:.0f}ms"
        elif seconds < 60:
            text = f"{seconds:.1f}秒"
        else:
            minutes = int(seconds // 60)
            secs = seconds % 60
            text = f"{minutes}分{secs:.0f}秒"
        
        self._time_label.setText(f"処理時間: {text}")
    
    def clear_time(self):
        """処理時間をクリア"""
        self._time_label.setText("")
    
    def set_ready(self):
        """準備完了状態にする"""
        self.set_message("準備完了")
        self.show_progress(False)
