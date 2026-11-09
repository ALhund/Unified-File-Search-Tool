"""拡張子選択ポップアップ"""

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QCheckBox,
    QPushButton,
    QLineEdit,
    QScrollArea,
    QFrame,
    QLabel,
)

from src.common.config import get_config


class ExtensionPopup(QFrame):
    """拡張子選択ポップアップ"""
    
    extensions_selected = Signal(list)
    
    # 定義済み拡張子（カテゴリ別）
    PRESET_EXTENSIONS = {
        "Office": ["docx", "xlsx", "xlsm", "pptx"],
        "PDF": ["pdf"],
        "テキスト": ["txt", "md", "log"],
    }
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent, Qt.WindowType.Popup)
        self._config = get_config()
        self._checkboxes: dict[str, QCheckBox] = {}
        self._available: list[str] = []
        self._setup_ui()
    
    def _setup_ui(self):
        """UIを構築"""
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setMinimumWidth(250)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # フィルタ入力
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("絞り込み...")
        self._filter_edit.textChanged.connect(self._apply_filter)
        layout.addWidget(self._filter_edit)
        
        # スクロールエリア
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(200)
        
        self._scroll_widget = QWidget()
        self._scroll_layout = QVBoxLayout(self._scroll_widget)
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.setSpacing(4)
        
        # プリセット拡張子を追加
        for category, extensions in self.PRESET_EXTENSIONS.items():
            label = QLabel(f"<b>{category}</b>")
            self._scroll_layout.addWidget(label)
            
            for ext in extensions:
                cb = QCheckBox(ext)
                self._checkboxes[ext] = cb
                self._scroll_layout.addWidget(cb)
        
        # フォルダ内の拡張子セクション（動的）
        self._dynamic_label = QLabel("<b>フォルダ内</b>")
        self._dynamic_label.hide()
        self._scroll_layout.addWidget(self._dynamic_label)
        
        self._scroll_layout.addStretch()
        
        scroll.setWidget(self._scroll_widget)
        layout.addWidget(scroll)
        
        # ボタン
        button_layout = QHBoxLayout()
        
        all_btn = QPushButton("すべて選択")
        all_btn.clicked.connect(self._select_all)
        button_layout.addWidget(all_btn)
        
        none_btn = QPushButton("すべて解除")
        none_btn.clicked.connect(self._select_none)
        button_layout.addWidget(none_btn)
        
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self._on_ok)
        button_layout.addWidget(ok_btn)
        
        layout.addLayout(button_layout)
    
    def set_available(self, extensions: list[str]):
        """フォルダ内で利用可能な拡張子を設定"""
        self._available = sorted(set(extensions))
        
        # 既存の動的チェックボックスを削除
        for ext in list(self._checkboxes.keys()):
            if ext not in self._get_preset_extensions():
                cb = self._checkboxes.pop(ext)
                cb.deleteLater()
        
        # 新しい拡張子を追加
        new_extensions = [
            ext for ext in self._available
            if ext not in self._get_preset_extensions()
        ]
        
        if new_extensions:
            self._dynamic_label.show()
            for ext in new_extensions:
                cb = QCheckBox(ext)
                self._checkboxes[ext] = cb
                # ストレッチの前に挿入
                self._scroll_layout.insertWidget(
                    self._scroll_layout.count() - 1,
                    cb
                )
        else:
            self._dynamic_label.hide()
    
    def _get_preset_extensions(self) -> list[str]:
        """プリセット拡張子を取得"""
        result = []
        for extensions in self.PRESET_EXTENSIONS.values():
            result.extend(extensions)
        return result
    
    def set_selected(self, extensions: list[str]):
        """選択状態を設定"""
        for ext, cb in self._checkboxes.items():
            cb.setChecked(ext in extensions)
    
    def get_selected(self) -> list[str]:
        """選択された拡張子を取得"""
        return [ext for ext, cb in self._checkboxes.items() if cb.isChecked()]
    
    def _apply_filter(self, text: str):
        """フィルタを適用"""
        text = text.lower()
        for ext, cb in self._checkboxes.items():
            cb.setVisible(text in ext.lower())
    
    def _select_all(self):
        """すべて選択"""
        for cb in self._checkboxes.values():
            if cb.isVisible():
                cb.setChecked(True)
    
    def _select_none(self):
        """すべて解除"""
        for cb in self._checkboxes.values():
            if cb.isVisible():
                cb.setChecked(False)
    
    def _on_ok(self):
        """OKボタン"""
        self.extensions_selected.emit(self.get_selected())
        self.hide()
