"""検索パネル

検索条件の入力エリアを提供する。
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QGroupBox,
    QFileDialog,
    QComboBox,
)

from src.common.config import get_config
from src.enumeration.file_enumerator import normalize_extensions
from src.ui.widgets.extension_popup import ExtensionPopup
from src.ui.widgets.regex_help_dialog import RegexHelpDialog

TERM_MODES = [
    ("and", "すべての語を含む (AND)"),
    ("or", "いずれかの語を含む (OR)"),
    ("phrase", "入力どおりの語句"),
]


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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        layout.addWidget(self._create_folder_group())
        layout.addWidget(self._create_condition_group())
        layout.addWidget(self._create_regex_group())
        
        # 検索ボタン
        button_layout = QHBoxLayout()
        
        self._search_btn = QPushButton("検索")
        self._search_btn.setMinimumHeight(36)
        self._search_btn.setDefault(True)
        self._search_btn.clicked.connect(self._on_search_clicked)
        button_layout.addWidget(self._search_btn, 2)
        
        self._cancel_btn = QPushButton("中断 (ESC)")
        self._cancel_btn.setMinimumHeight(36)
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self.cancel_requested.emit)
        button_layout.addWidget(self._cancel_btn, 1)
        
        layout.addLayout(button_layout)
    
    def _create_folder_group(self) -> QGroupBox:
        """検索対象フォルダグループ"""
        group = QGroupBox("検索対象フォルダ")
        layout = QHBoxLayout(group)
        
        self._folder_edit = QLineEdit()
        self._folder_edit.setPlaceholderText("フォルダを選択してください")
        self._folder_edit.returnPressed.connect(self._on_search_clicked)
        layout.addWidget(self._folder_edit)
        
        browse_btn = QPushButton("参照...")
        browse_btn.clicked.connect(self._on_browse_folder)
        layout.addWidget(browse_btn)
        
        self._subfolder_check = QCheckBox("サブフォルダも")
        self._subfolder_check.setChecked(self._config.search_defaults.include_subfolders)
        layout.addWidget(self._subfolder_check)
        
        return group
    
    def _create_condition_group(self) -> QGroupBox:
        """検索条件グループ"""
        group = QGroupBox("検索条件")
        grid = QGridLayout(group)
        grid.setColumnStretch(1, 1)
        
        # 検索語
        grid.addWidget(QLabel("検索語:"), 0, 0)
        self._keyword_edit = QLineEdit()
        self._keyword_edit.setPlaceholderText('空白区切りで複数指定（語句は "..." で囲む）')
        self._keyword_edit.setClearButtonEnabled(True)
        self._keyword_edit.returnPressed.connect(self._on_search_clicked)
        grid.addWidget(self._keyword_edit, 0, 1)
        
        self._mode_combo = QComboBox()
        for value, label in TERM_MODES:
            self._mode_combo.addItem(label, value)
        self._mode_combo.setToolTip("複数の語を入力したときの扱い")
        grid.addWidget(self._mode_combo, 0, 2)
        
        # オプション
        option_layout = QHBoxLayout()
        defaults = self._config.search_defaults
        
        self._regex_check = QCheckBox("正規表現")
        self._regex_check.setChecked(defaults.use_regex)
        self._regex_check.toggled.connect(self._on_regex_toggled)
        option_layout.addWidget(self._regex_check)
        
        self._case_check = QCheckBox("大文字/小文字を区別")
        self._case_check.setChecked(
            defaults.case_sensitive or not self._config.regex_options.ignore_case
        )
        option_layout.addWidget(self._case_check)
        
        self._width_check = QCheckBox("全角/半角を区別")
        self._width_check.setToolTip(
            "オフの場合、「ＡＢＣ」と「ABC」、「ｶﾀｶﾅ」と「カタカナ」を同じものとして検索します"
        )
        option_layout.addWidget(self._width_check)
        
        self._whole_check = QCheckBox("完全一致")
        self._whole_check.setToolTip("セル・行・段落の全体が検索語と一致するものだけを対象にします")
        self._whole_check.setChecked(defaults.match_whole)
        option_layout.addWidget(self._whole_check)
        
        option_layout.addStretch()
        grid.addLayout(option_layout, 1, 1, 1, 2)
        
        # 除外語
        grid.addWidget(QLabel("除外語:"), 2, 0)
        self._exclude_edit = QLineEdit()
        self._exclude_edit.setPlaceholderText("この語を含む箇所は除外（カンマ区切り）")
        self._exclude_edit.returnPressed.connect(self._on_search_clicked)
        grid.addWidget(self._exclude_edit, 2, 1, 1, 2)
        
        # 対象拡張子
        grid.addWidget(QLabel("拡張子:"), 3, 0)
        ext_layout = QHBoxLayout()
        self._extension_edit = QLineEdit()
        self._extension_edit.setPlaceholderText("例: xlsx,docx,pdf")
        self._extension_edit.setText(",".join(self._config.target_extensions))
        ext_layout.addWidget(self._extension_edit)
        
        self._ext_btn = QPushButton("▼")
        self._ext_btn.setFixedWidth(30)
        self._ext_btn.clicked.connect(self._show_extension_popup)
        ext_layout.addWidget(self._ext_btn)
        grid.addLayout(ext_layout, 3, 1, 1, 2)
        
        return group
    
    def _create_regex_group(self) -> QGroupBox:
        """正規表現オプショングループ"""
        group = QGroupBox("正規表現オプション")
        self._regex_group = group
        layout = QVBoxLayout(group)
        
        option_layout = QHBoxLayout()
        
        self._multiline_check = QCheckBox("複数行モード（^ $ を行単位に）")
        self._multiline_check.setChecked(self._config.regex_options.multiline)
        option_layout.addWidget(self._multiline_check)
        
        self._dotall_check = QCheckBox(". を改行にもマッチ")
        self._dotall_check.setChecked(self._config.regex_options.dot_matches_newline)
        option_layout.addWidget(self._dotall_check)
        
        option_layout.addStretch()
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
        
        help_btn = QPushButton("?")
        help_btn.setFixedWidth(30)
        help_btn.setToolTip("正規表現ヘルプ")
        help_btn.clicked.connect(self._show_regex_help)
        insert_layout.addWidget(help_btn)
        
        layout.addLayout(insert_layout)
        
        self._on_regex_toggled(self._regex_check.isChecked())
        return group
    
    def _on_regex_toggled(self, checked: bool):
        """正規表現モードでは使えない項目を無効にする"""
        self._mode_combo.setEnabled(not checked)
        self._whole_check.setEnabled(not checked)
        self._multiline_check.setEnabled(checked)
        self._dotall_check.setEnabled(checked)
    
    def _on_browse_folder(self):
        """フォルダ参照"""
        folder = QFileDialog.getExistingDirectory(
            self,
            "検索対象フォルダを選択",
            self._folder_edit.text() or str(Path.home()),
        )
        if folder:
            self._folder_edit.setText(folder)
    
    def _current_extensions(self) -> list[str]:
        return sorted(normalize_extensions(self._extension_edit.text().split(",")))
    
    def _show_extension_popup(self):
        """拡張子ポップアップを表示"""
        if self._extension_popup is None:
            self._extension_popup = ExtensionPopup(self)
            self._extension_popup.extensions_selected.connect(self._on_extensions_selected)
        
        self._extension_popup.set_selected(self._current_extensions())
        
        pos = self._ext_btn.mapToGlobal(self._ext_btn.rect().bottomLeft())
        self._extension_popup.move(pos)
        self._extension_popup.show()
    
    def _on_extensions_selected(self, extensions: list[str]):
        """拡張子が選択された"""
        self._extension_edit.setText(",".join(sorted(normalize_extensions(extensions))))
    
    def _insert_pattern(self, pattern: str):
        """パターンを挿入"""
        cursor = self._keyword_edit.cursorPosition()
        current = self._keyword_edit.text()
        self._keyword_edit.setText(current[:cursor] + pattern + current[cursor:])
        
        # カッコ付きパターンの場合は中にカーソルを置く
        offset = len(pattern) - 1 if pattern.endswith(")") else len(pattern)
        self._keyword_edit.setCursorPosition(cursor + offset)
        
        self._regex_check.setChecked(True)
        self._keyword_edit.setFocus()
    
    def _show_regex_help(self):
        """正規表現ヘルプダイアログを表示"""
        RegexHelpDialog(self).exec()
    
    def _on_search_clicked(self):
        """検索ボタンクリック"""
        if not self._search_btn.isEnabled():
            return
        self.search_requested.emit(self.get_conditions())
    
    def get_conditions(self) -> dict:
        """入力されている検索条件"""
        return {
            "folder": self._folder_edit.text().strip().strip('"'),
            "include_subfolders": self._subfolder_check.isChecked(),
            "keyword": self._keyword_edit.text(),
            "term_mode": self._mode_combo.currentData(),
            "use_regex": self._regex_check.isChecked(),
            "case_sensitive": self._case_check.isChecked(),
            "ignore_width": not self._width_check.isChecked(),
            "match_whole": self._whole_check.isChecked(),
            "exclude_words": [
                word.strip()
                for word in self._exclude_edit.text().replace("、", ",").split(",")
                if word.strip()
            ],
            "extensions": self._current_extensions(),
            "multiline": self._multiline_check.isChecked(),
            "dotall": self._dotall_check.isChecked(),
        }
    
    def set_searching(self, searching: bool):
        """検索中状態を設定"""
        self._search_btn.setEnabled(not searching)
        self._cancel_btn.setEnabled(searching)
    
    def get_search_folder(self) -> str:
        """検索フォルダを取得"""
        return self._folder_edit.text()
    
    def set_search_folder(self, folder: str):
        """検索フォルダを設定"""
        self._folder_edit.setText(folder)
    
    def set_keyword(self, keyword: str):
        """検索語を設定"""
        self._keyword_edit.setText(keyword)
    
    def focus_keyword(self):
        """検索語の入力欄にフォーカスを移す"""
        self._keyword_edit.setFocus()
        self._keyword_edit.selectAll()
