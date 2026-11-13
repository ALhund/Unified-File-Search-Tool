"""検索バー（画面上部）

フォルダ選択・検索語・検索方法・ファイル種類・条件をまとめた領域。
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, QStringListModel, Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.common.config import get_config
from src.ui import icons
from src.ui.settings import MATCH_LIMIT_CHOICES, limit_label
from src.ui.widgets.common import chip, divider, ghost_button, label, primary_button

# ファイル種類のまとまり: (キー, 表示名, 拡張子, アイコンに使う拡張子)
TYPE_GROUPS: list[tuple[str, str, tuple[str, ...], str]] = [
    ("excel", "Excel", ("xlsx", "xlsm"), "xlsx"),
    ("word", "Word", ("docx",), "docx"),
    ("powerpoint", "PowerPoint", ("pptx",), "pptx"),
    ("pdf", "PDF", ("pdf",), "pdf"),
    ("text", "テキスト", ("txt", "md", "log"), "txt"),
]

SEARCH_MODES = [
    ("and", "すべての語を含む", "空白で区切った語が、すべて同じファイルにあるものを探します"),
    ("or", "いずれかの語を含む", "空白で区切った語のどれか1つでもあるものを探します"),
    ("phrase", "入力どおりの語句", "空白も含め、入力したとおりの語句を探します"),
    ("regex", "正規表現", "正規表現で探します"),
]

REGEX_SNIPPETS = [
    (".*", ".*", "任意の文字列"),
    ("\\s*", "\\s*", "0個以上の空白"),
    ("\\d+", "\\d+", "1個以上の数字"),
    ("^", "^", "行頭"),
    ("$", "$", "行末"),
    ("|", "|", "または"),
    ("( )", "()", "グループ"),
    ("(?: )", "(?:)", "非キャプチャグループ"),
]


class SearchBar(QFrame):
    """画面上部の検索バー"""
    
    search_requested = Signal()
    cancel_requested = Signal()
    folder_changed = Signal(str)
    types_changed = Signal()
    settings_requested = Signal()
    theme_requested = Signal(str)  # system / light / dark
    shortcuts_requested = Signal()
    regex_help_requested = Signal()
    about_requested = Signal()
    license_requested = Signal()
    match_limit_changed = Signal(int)  # 利用者が上限を変えたとき
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("AppBar")
        self._searching = False
        self._recent_folders: list[str] = []
        self._folder_timer = QTimer(self, singleShot=True, interval=450)
        self._folder_timer.timeout.connect(self._emit_folder_changed)
        self._last_emitted_folder = ""
        self._setup_ui()
    
    # ------------------------------------------------------------------
    # 構築
    # ------------------------------------------------------------------
    
    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 10, 16, 12)
        root.setSpacing(10)
        
        root.addLayout(self._build_title_row())
        root.addLayout(self._build_query_row())
        root.addLayout(self._build_filter_row())
        root.addWidget(self._build_advanced_panel())
    
    def _build_title_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        
        self._logo = QLabel()
        self._logo.setPixmap(icons.app_icon().pixmap(QSize(28, 28)))
        row.addWidget(self._logo)
        
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(label("Unified File Search", "AppTitle"))
        titles.addWidget(label("Office・PDF・テキストをまとめて検索", "AppSubtitle"))
        row.addLayout(titles)
        row.addStretch(1)
        
        self._theme_btn = ghost_button("sun", "テーマ")
        self._theme_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        theme_menu = QMenu(self._theme_btn)
        self._theme_actions: dict[str, QAction] = {}
        for value, text in (("system", "Windows の設定に合わせる"), ("light", "ライト"), ("dark", "ダーク")):
            action = theme_menu.addAction(text)
            action.setCheckable(True)
            action.triggered.connect(lambda _=False, v=value: self.theme_requested.emit(v))
            self._theme_actions[value] = action
        self._theme_btn.setMenu(theme_menu)
        row.addWidget(self._theme_btn)
        
        help_btn = ghost_button("help", "ヘルプ")
        help_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        help_menu = QMenu(help_btn)
        help_menu.addAction(icons.icon("keyboard"), "キーボード ショートカット\tF1", self.shortcuts_requested.emit)
        help_menu.addAction(icons.icon("regex"), "正規表現の書き方", self.regex_help_requested.emit)
        help_menu.addSeparator()
        help_menu.addAction(icons.icon("key"), "ライセンスの登録…", self.license_requested.emit)
        help_menu.addAction(icons.icon("info"), "バージョン情報", self.about_requested.emit)
        help_btn.setMenu(help_menu)
        self._help_menu = help_menu
        row.addWidget(help_btn)
        
        settings_btn = ghost_button("settings", "設定 (Ctrl+,)")
        settings_btn.clicked.connect(self.settings_requested.emit)
        row.addWidget(settings_btn)
        return row
    
    def _build_query_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        
        # フォルダ
        self._folder_edit = QLineEdit()
        self._folder_edit.setPlaceholderText("検索するフォルダ（ドラッグ＆ドロップでも指定できます）")
        self._folder_edit.setMinimumWidth(260)
        self._folder_action = self._folder_edit.addAction(
            icons.icon("folder", "secondary"), QLineEdit.ActionPosition.LeadingPosition
        )
        self._recent_action = self._folder_edit.addAction(
            icons.icon("history", "secondary"), QLineEdit.ActionPosition.TrailingPosition
        )
        self._recent_action.setToolTip("最近使ったフォルダ")
        self._recent_action.triggered.connect(self._show_recent_folders)
        self._folder_edit.textChanged.connect(lambda _: self._folder_timer.start())
        self._folder_edit.editingFinished.connect(self._emit_folder_changed)
        self._folder_edit.returnPressed.connect(self._on_search_clicked)
        row.addWidget(self._folder_edit, 4)
        
        browse = QPushButton("参照…")
        browse.setToolTip("フォルダを選ぶ (Ctrl+O)")
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        icons.bind(browse, "folder-open", "text", 16)
        browse.clicked.connect(self.browse_folder)
        row.addWidget(browse)
        
        row.addSpacing(6)
        
        # 検索語
        self._query_edit = QLineEdit()
        self._query_edit.setObjectName("SearchBox")
        self._query_edit.setPlaceholderText('検索語を入力（空白区切りで複数・"…" で語句）')
        self._query_edit.setClearButtonEnabled(True)
        self._search_action = self._query_edit.addAction(
            icons.icon("search", "secondary"), QLineEdit.ActionPosition.LeadingPosition
        )
        self._query_edit.returnPressed.connect(self._on_search_clicked)
        self._query_model = QStringListModel(self)
        completer = QCompleter(self._query_model, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._query_edit.setCompleter(completer)
        row.addWidget(self._query_edit, 7)
        
        self._mode_combo = QComboBox()
        for value, text, tooltip in SEARCH_MODES:
            self._mode_combo.addItem(text, value)
            self._mode_combo.setItemData(self._mode_combo.count() - 1, tooltip, Qt.ItemDataRole.ToolTipRole)
        self._mode_combo.setToolTip("複数の語の扱い・正規表現")
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self._mode_combo.setMinimumWidth(170)
        row.addWidget(self._mode_combo)
        
        self._search_btn = primary_button("検索", "search")
        self._search_btn.setMinimumWidth(104)
        self._search_btn.setToolTip("検索 (Enter)")
        self._search_btn.clicked.connect(self._on_search_clicked)
        row.addWidget(self._search_btn)
        return row
    
    def _build_filter_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        
        enabled = set(get_config().target_extensions)
        self._type_chips: dict[str, QToolButton] = {}
        for key, name, extensions, icon_ext in TYPE_GROUPS:
            button = chip(name, tooltip=f"{name}（{', '.join('.' + e for e in extensions)}）を対象にする")
            button.setIcon(icons.file_icon(icon_ext, 18))
            button.setIconSize(QSize(18, 18))
            button.setChecked(any(e in enabled for e in extensions))
            button.toggled.connect(lambda _=False: self.types_changed.emit())
            button.setProperty("type_name", name)
            self._type_chips[key] = button
            row.addWidget(button)
        
        row.addSpacing(4)
        row.addWidget(divider())
        row.addSpacing(4)
        
        defaults = get_config().search_defaults
        self._case_chip = chip("大/小文字", "case", "大文字と小文字を区別する")
        self._case_chip.setChecked(defaults.case_sensitive)
        self._width_chip = chip("全/半角", "width", "全角と半角を区別する（オフなら ＡＢＣ と ABC、ｶﾅ と カナ を同じとみなす）")
        self._whole_chip = chip("完全一致", "whole", "セル・行・段落の全体が検索語と一致するものだけ")
        self._whole_chip.setChecked(defaults.match_whole)
        self._subfolder_chip = chip("サブフォルダ", "subfolder", "サブフォルダの中も検索する")
        self._subfolder_chip.setChecked(defaults.include_subfolders)
        self._subfolder_chip.toggled.connect(lambda _: self._folder_timer.start())
        for button in (self._case_chip, self._width_chip, self._whole_chip, self._subfolder_chip):
            row.addWidget(button)
        
        row.addStretch(1)
        
        self._advanced_chip = chip("詳細条件", "sliders", "除外語・1ファイルの上限件数・正規表現のオプション")
        self._advanced_chip.toggled.connect(self._on_advanced_toggled)
        row.addWidget(self._advanced_chip)
        return row
    
    def _build_advanced_panel(self) -> QWidget:
        panel = QWidget()
        self._advanced_panel = panel
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        layout.addWidget(label("除外語", "Secondary"))
        self._exclude_edit = QLineEdit()
        self._exclude_edit.setPlaceholderText("この語を含むセル・行・段落は除く（カンマ区切り）")
        self._exclude_edit.addAction(icons.icon("exclude", "secondary"), QLineEdit.ActionPosition.LeadingPosition)
        self._exclude_edit.setClearButtonEnabled(True)
        self._exclude_edit.returnPressed.connect(self._on_search_clicked)
        layout.addWidget(self._exclude_edit, 3)
        
        layout.addSpacing(8)
        layout.addWidget(label("1ファイルの上限", "Secondary"))
        self._limit_combo = QComboBox()
        self._limit_combo.setToolTip("1ファイルあたり何件まで数えるか。上限に達したファイルは「50+」のように表示します")
        for value in MATCH_LIMIT_CHOICES:
            self._limit_combo.addItem(limit_label(value), value)
        self._limit_combo.setMinimumWidth(110)
        self._limit_combo.activated.connect(lambda _: self.match_limit_changed.emit(self.match_limit()))
        layout.addWidget(self._limit_combo)
        self.set_match_limit(get_config().search_max_matches_per_file)
        
        self._regex_box = QWidget()
        regex_layout = QHBoxLayout(self._regex_box)
        regex_layout.setContentsMargins(0, 0, 0, 0)
        regex_layout.setSpacing(6)
        regex_layout.addWidget(divider())
        regex_options = get_config().regex_options
        self._multiline_check = QCheckBox("^ $ を行ごとに")
        self._multiline_check.setChecked(regex_options.multiline)
        self._multiline_check.setToolTip("複数行モード（MULTILINE）")
        self._dotall_check = QCheckBox(". を改行にも")
        self._dotall_check.setChecked(regex_options.dot_matches_newline)
        self._dotall_check.setToolTip("DOTALL")
        regex_layout.addWidget(self._multiline_check)
        regex_layout.addWidget(self._dotall_check)
        for text, pattern, tooltip in REGEX_SNIPPETS:
            button = QToolButton()
            button.setText(text)
            button.setToolTip(f"{tooltip} を挿入")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, p=pattern: self._insert_pattern(p))
            regex_layout.addWidget(button)
        help_btn = ghost_button("help", "正規表現の書き方", size=16)
        help_btn.clicked.connect(self.regex_help_requested.emit)
        regex_layout.addWidget(help_btn)
        layout.addWidget(self._regex_box)
        layout.addStretch(1)
        
        panel.hide()
        self._on_mode_changed()
        return panel
    
    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------
    
    def browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "検索するフォルダを選択", self.folder() or str(Path.home())
        )
        if folder:
            self.set_folder(folder)
            self._query_edit.setFocus()
    
    def _show_recent_folders(self) -> None:
        menu = QMenu(self)
        if not self._recent_folders:
            action = menu.addAction("最近使ったフォルダはありません")
            action.setEnabled(False)
        for folder in self._recent_folders:
            action = menu.addAction(icons.icon("folder", "secondary"), folder)
            action.triggered.connect(lambda _=False, f=folder: self.set_folder(f))
        menu.setMinimumWidth(self._folder_edit.width())
        menu.exec(self._folder_edit.mapToGlobal(self._folder_edit.rect().bottomLeft()))
    
    def _emit_folder_changed(self) -> None:
        self._folder_timer.stop()
        folder = self.folder()
        key = f"{folder}|{self._subfolder_chip.isChecked()}"
        if key != self._last_emitted_folder:
            self._last_emitted_folder = key
            self.folder_changed.emit(folder)
    
    def _on_mode_changed(self) -> None:
        regex = self.mode() == "regex"
        self._whole_chip.setEnabled(not regex)
        if hasattr(self, "_regex_box"):
            self._regex_box.setVisible(regex)
            if regex and not self._advanced_chip.isChecked():
                self._advanced_chip.setChecked(True)
        self._query_edit.setPlaceholderText(
            "正規表現を入力（例: \\d{3}-\\d{4}）" if regex
            else '検索語を入力（空白区切りで複数・"…" で語句）'
        )
    
    def _on_advanced_toggled(self, checked: bool) -> None:
        self._advanced_panel.setVisible(checked)
    
    def _insert_pattern(self, pattern: str) -> None:
        cursor = self._query_edit.cursorPosition()
        text = self._query_edit.text()
        self._query_edit.setText(text[:cursor] + pattern + text[cursor:])
        offset = len(pattern) - 1 if pattern.endswith(")") else len(pattern)
        self._query_edit.setCursorPosition(cursor + offset)
        self._query_edit.setFocus()
    
    def _on_search_clicked(self) -> None:
        if self._searching:
            return
        self.search_requested.emit()
    
    # ------------------------------------------------------------------
    # 状態の読み書き
    # ------------------------------------------------------------------
    
    def set_searching(self, searching: bool) -> None:
        self._searching = searching
        try:
            self._search_btn.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        if searching:
            self._search_btn.setText("中断")
            self._search_btn.setObjectName("")
            self._search_btn.setToolTip("検索を中断 (Esc)")
            icons.rebind(self._search_btn, "stop", "text")
            self._search_btn.clicked.connect(self.cancel_requested.emit)
        else:
            self._search_btn.setText("検索")
            self._search_btn.setObjectName("Primary")
            self._search_btn.setToolTip("検索 (Enter)")
            icons.rebind(self._search_btn, "search", "on_accent")
            self._search_btn.clicked.connect(self._on_search_clicked)
        # objectName の変更をスタイルに反映する
        self._search_btn.style().unpolish(self._search_btn)
        self._search_btn.style().polish(self._search_btn)
    
    def folder(self) -> str:
        return self._folder_edit.text().strip().strip('"')
    
    def set_folder(self, folder: str) -> None:
        self._folder_edit.setText(folder)
        self._emit_folder_changed()
    
    def query(self) -> str:
        return self._query_edit.text()
    
    def set_query(self, text: str) -> None:
        self._query_edit.setText(text)
    
    def mode(self) -> str:
        return self._mode_combo.currentData()
    
    def focus_query(self) -> None:
        self._query_edit.setFocus()
        self._query_edit.selectAll()
    
    def set_folder_valid(self, valid: bool) -> None:
        self._folder_edit.setToolTip("" if valid else "フォルダが見つかりません")
        self._folder_action.setIcon(icons.icon("folder" if valid else "warning", "secondary" if valid else "danger"))
    
    def set_recent_folders(self, folders: list[str]) -> None:
        self._recent_folders = folders
    
    def set_query_history(self, queries: list[str]) -> None:
        self._query_model.setStringList(queries)
    
    def set_theme_mode(self, mode: str, dark: bool) -> None:
        for value, action in self._theme_actions.items():
            action.setChecked(value == mode)
        icons.rebind(self._theme_btn, "moon" if dark else "sun")
    
    def set_match_limit(self, value: int) -> None:
        index = self._limit_combo.findData(value)
        if index < 0:
            self._limit_combo.addItem(limit_label(value), value)
            index = self._limit_combo.count() - 1
        self._limit_combo.setCurrentIndex(index)
    
    def match_limit(self) -> int:
        return int(self._limit_combo.currentData())
    
    def selected_extensions(self) -> set[str]:
        selected: set[str] = set()
        for key, _, extensions, _ in TYPE_GROUPS:
            if self._type_chips[key].isChecked():
                selected.update(extensions)
        return selected
    
    def include_subfolders(self) -> bool:
        return self._subfolder_chip.isChecked()
    
    def set_type_counts(self, counts: Optional[dict[str, int]]) -> None:
        """フォルダ内のファイル数を種類ごとに表示する（None なら数を消す）"""
        for key, name, extensions, _ in TYPE_GROUPS:
            button = self._type_chips[key]
            if counts is None:
                button.setText(name)
            else:
                button.setText(f"{name}  {sum(counts.get(e, 0) for e in extensions):,}")
    
    def conditions(self) -> dict:
        regex = self.mode() == "regex"
        return {
            "folder": self.folder(),
            "include_subfolders": self.include_subfolders(),
            "keyword": self.query(),
            "term_mode": "and" if regex else self.mode(),
            "use_regex": regex,
            "case_sensitive": self._case_chip.isChecked(),
            "ignore_width": not self._width_chip.isChecked(),
            "match_whole": self._whole_chip.isChecked() and not regex,
            "exclude_words": [
                w.strip() for w in self._exclude_edit.text().replace("、", ",").split(",") if w.strip()
            ],
            "extensions": sorted(self.selected_extensions()),
            "multiline": self._multiline_check.isChecked(),
            "dotall": self._dotall_check.isChecked(),
            "match_limit": self.match_limit(),
        }
    
    def state(self) -> dict:
        """次回起動時に復元する状態"""
        return {
            "mode": self.mode(),
            "case": self._case_chip.isChecked(),
            "width": self._width_chip.isChecked(),
            "whole": self._whole_chip.isChecked(),
            "subfolders": self._subfolder_chip.isChecked(),
            "types": [k for k, b in self._type_chips.items() if b.isChecked()],
            "advanced": self._advanced_chip.isChecked(),
            "multiline": self._multiline_check.isChecked(),
            "dotall": self._dotall_check.isChecked(),
        }
    
    def restore_state(self, state: dict) -> None:
        def flag(key: str, default: bool) -> bool:
            value = state.get(key, default)
            return value if isinstance(value, bool) else str(value).lower() == "true"
        
        if state.get("mode"):
            index = self._mode_combo.findData(state["mode"])
            if index >= 0:
                self._mode_combo.setCurrentIndex(index)
        self._case_chip.setChecked(flag("case", self._case_chip.isChecked()))
        self._width_chip.setChecked(flag("width", self._width_chip.isChecked()))
        self._whole_chip.setChecked(flag("whole", self._whole_chip.isChecked()))
        self._subfolder_chip.setChecked(flag("subfolders", self._subfolder_chip.isChecked()))
        self._multiline_check.setChecked(flag("multiline", self._multiline_check.isChecked()))
        self._dotall_check.setChecked(flag("dotall", self._dotall_check.isChecked()))
        types = state.get("types")
        if isinstance(types, str):
            types = [types]
        if types:
            for key, button in self._type_chips.items():
                button.setChecked(key in types)
        self._advanced_chip.setChecked(flag("advanced", False) or self.mode() == "regex")
