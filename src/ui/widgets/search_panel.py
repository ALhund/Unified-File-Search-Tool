"""検索パネル

検索条件の入力エリアを提供する。
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QGroupBox,
    QFileDialog,
    QComboBox,
    QFrame,
)

from src.common.config import get_config
from src.ui.widgets.extension_popup import ExtensionPopup
from src.ui.widgets.regex_help_dialog import RegexHelpDialog


class SearchPanel(QWidget):
    """検索パネル"""
    
    # シグナル
    search_requested = Signal(dict)  # 検索条件を渡す
    cancel_requested = Signal()
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._config = get_config()
        self._extension_popup: Optional[ExtensionPopup] = None
        self._setup_ui()
    
    def _setup_ui(self):
        """UIを構築"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # 検索対象フォルダ
        folder_group = self._create_folder_group()
        layout.addWidget(folder_group)
        
        # 検索条件
        condition_group = self._create_condition_group()
        layout.addWidget(condition_group)
        
        # 正規表現オプション
        regex_group = self._create_regex_group()
        layout.addWidget(regex_group)
        
        # 検索ボタン
        button_layout = QHBoxLayout()
        
        self._search_btn = QPushButton("検索")
        self._search_btn.setMinimumHeight(36)
        self._search_btn.clicked.connect(self._on_search_clicked)
        button_layout.addWidget(self._search_btn)
        
        self._cancel_btn = QPushButton("中断 (ESC)")
        self._cancel_btn.setMinimumHeight(36)
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel_clicked)
        button_layout.addWidget(self._cancel_btn)
        
        layout.addLayout(button_layout)
        
        # 余白
        layout.addStretch()
    
    def _create_folder_group(self) -> QGroupBox:
        """検索対象フォルダグループ"""
        group = QGroupBox("検索対象フォルダ")
        layout = QHBoxLayout(group)
        
        self._folder_edit = QLineEdit()
        self._folder_edit.setPlaceholderText("フォルダを選択してください")
        layout.addWidget(self._folder_edit)
        
        browse_btn = QPushButton("参照...")
        browse_btn.clicked.connect(self._on_browse_folder)
        layout.addWidget(browse_btn)
        
        return group
    
    def _create_condition_group(self) -> QGroupBox:
        """検索条件グループ"""
        group = QGroupBox("検索条件")
        layout = QVBoxLayout(group)
        
        # 検索語
        keyword_layout = QHBoxLayout()
        keyword_layout.addWidget(QLabel("検索語:"))
        
        self._keyword_edit = QLineEdit()
        self._keyword_edit.setPlaceholderText("検索キーワードを入力")
        self._keyword_edit.returnPressed.connect(self._on_search_clicked)
        keyword_layout.addWidget(self._keyword_edit)
        
        self._regex_check = QCheckBox("正規表現")
        keyword_layout.addWidget(self._regex_check)
        
        layout.addLayout(keyword_layout)
        
        # 除外語
        exclude_layout = QHBoxLayout()
        exclude_layout.addWidget(QLabel("除外語:"))
        
        self._exclude_edit = QLineEdit()
        self._exclude_edit.setPlaceholderText("除外キーワード（カンマ区切り）")
        exclude_layout.addWidget(self._exclude_edit)
        
        layout.addLayout(exclude_layout)
        
        # 対象拡張子
        ext_layout = QHBoxLayout()
        ext_layout.addWidget(QLabel("対象拡張子:"))
        
        self._extension_edit = QLineEdit()
        self._extension_edit.setPlaceholderText("例: .txt,.md,.docx")
        self._extension_edit.setText(",".join(self._config.target_extensions))
        ext_layout.addWidget(self._extension_edit)
        
        self._ext_btn = QPushButton("▼")
        self._ext_btn.setFixedWidth(30)
        self._ext_btn.clicked.connect(self._show_extension_popup)
        ext_layout.addWidget(self._ext_btn)
        
        layout.addLayout(ext_layout)
        
        return group
    
    def _create_regex_group(self) -> QGroupBox:
        """正規表現オプショングループ"""
        group = QGroupBox("正規表現オプション")
        layout = QVBoxLayout(group)
        
        # オプションチェックボックス
        option_layout = QHBoxLayout()
        
        self._ignore_case_check = QCheckBox("大文字小文字を無視")
        self._ignore_case_check.setChecked(True)
        option_layout.addWidget(self._ignore_case_check)
        
        self._multiline_check = QCheckBox("複数行モード")
        option_layout.addWidget(self._multiline_check)
        
        self._dotall_check = QCheckBox("ドットが改行にもマッチ")
        option_layout.addWidget(self._dotall_check)
        
        layout.addLayout(option_layout)
        
        # 挿入ボタン（少数精鋭8個）
        insert_layout = QHBoxLayout()
        insert_layout.addWidget(QLabel("挿入:"))
        
        patterns = [
            (".*", ".*", "任意の文字列"),
            ("\\s*", "\\s*", "0個以上の空白"),
            ("\\d+", "\\d+", "1個以上の数字"),
            ("^", "^", "行頭"),
            ("$", "$", "行末"),
            ("|", "|", "または"),
            ("(...)", "()", "キャプチャグループ"),
            ("(?:...)", "(?:)", "非キャプチャグループ"),
        ]
        
        for label, pattern, tooltip in patterns:
            btn = QPushButton(label)
            btn.setToolTip(tooltip)
            btn.setFixedWidth(50)
            btn.clicked.connect(lambda _, p=pattern: self._insert_pattern(p))
            insert_layout.addWidget(btn)
        
        insert_layout.addStretch()
        
        # ヘルプボタン
        help_btn = QPushButton("?")
        help_btn.setFixedWidth(30)
        help_btn.setToolTip("正規表現ヘルプ")
        help_btn.clicked.connect(self._show_regex_help)
        insert_layout.addWidget(help_btn)
        
        layout.addLayout(insert_layout)
        
        return group
    
    def _on_browse_folder(self):
        """フォルダ参照"""
        folder = QFileDialog.getExistingDirectory(
            self,
            "検索対象フォルダを選択",
            self._folder_edit.text() or str(Path.home()),
        )
        if folder:
            self._folder_edit.setText(folder)
    
    def _show_extension_popup(self):
        """拡張子ポップアップを表示"""
        if self._extension_popup is None:
            self._extension_popup = ExtensionPopup(self)
            self._extension_popup.extensions_selected.connect(self._on_extensions_selected)
        
        # 現在の選択を設定
        current = [ext.strip() for ext in self._extension_edit.text().split(",") if ext.strip()]
        self._extension_popup.set_selected(current)
        
        # ボタンの下に表示
        pos = self._ext_btn.mapToGlobal(self._ext_btn.rect().bottomLeft())
        self._extension_popup.move(pos)
        self._extension_popup.show()
    
    def _on_extensions_selected(self, extensions: list[str]):
        """拡張子が選択された"""
        self._extension_edit.setText(",".join(extensions))
    
    def _insert_pattern(self, pattern: str):
        """パターンを挿入"""
        cursor = self._keyword_edit.cursorPosition()
        current = self._keyword_edit.text()
        
        # カッコ付きパターンの場合は中にカーソルを置く
        if pattern.endswith("()"):
            new_text = current[:cursor] + pattern + current[cursor:]
            self._keyword_edit.setText(new_text)
            self._keyword_edit.setCursorPosition(cursor + len(pattern) - 1)
        else:
            new_text = current[:cursor] + pattern + current[cursor:]
            self._keyword_edit.setText(new_text)
            self._keyword_edit.setCursorPosition(cursor + len(pattern))
        
        # 正規表現モードをオンに
        self._regex_check.setChecked(True)
        self._keyword_edit.setFocus()
    
    def _show_regex_help(self):
        """正規表現ヘルプダイアログを表示"""
        dialog = RegexHelpDialog(self)
        dialog.exec()
    
    def _on_search_clicked(self):
        """検索ボタンクリック"""
        # 検索条件を収集
        conditions = {
            "folder": self._folder_edit.text(),
            "keyword": self._keyword_edit.text(),
            "is_regex": self._regex_check.isChecked(),
            "exclude_keywords": [
                kw.strip()
                for kw in self._exclude_edit.text().split(",")
                if kw.strip()
            ],
            "extensions": [
                ext.strip()
                for ext in self._extension_edit.text().split(",")
                if ext.strip()
            ],
            "ignore_case": self._ignore_case_check.isChecked(),
            "multiline": self._multiline_check.isChecked(),
            "dotall": self._dotall_check.isChecked(),
        }
        
        self.search_requested.emit(conditions)
    
    def _on_cancel_clicked(self):
        """中断ボタンクリック"""
        self.cancel_requested.emit()
    
    def set_searching(self, searching: bool):
        """検索中状態を設定"""
        self._search_btn.setEnabled(not searching)
        self._cancel_btn.setEnabled(searching)
    
    def update_available_extensions(self, extensions: list[str]):
        """利用可能な拡張子を更新（フォルダ走査後）"""
        if self._extension_popup:
            self._extension_popup.set_available(extensions)
    
    def get_search_folder(self) -> str:
        """検索フォルダを取得"""
        return self._folder_edit.text()
    
    def set_search_folder(self, folder: str):
        """検索フォルダを設定"""
        self._folder_edit.setText(folder)
