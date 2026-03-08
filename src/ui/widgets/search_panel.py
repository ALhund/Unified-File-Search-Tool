"""検索パネル。

検索条件の入力エリアを提供する。
検索ボタンクリック時に :attr:`SearchPanel.search_requested` シグナルを発行する。
"""

from pathlib import Path

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
)

from src.common.config import get_config
from src.ui.widgets.extension_popup import ExtensionPopup
from src.ui.widgets.regex_help_dialog import RegexHelpDialog


class SearchPanel(QWidget):
    """検索パネル。

    フォルダ選択・キーワード入力・拡張子フィルタ・正規表現オプションを
    まとめた入力エリア。検索ボタンクリック時に :attr:`search_requested` を、
    中断ボタンクリック時に :attr:`cancel_requested` を発行する。

    Signals:
        search_requested: 検索条件 dict を持つシグナル。
            ``{"folder", "keyword", "is_regex", "exclude_keywords",
            "extensions", "ignore_case", "multiline", "dotall"}`` を含む。
        cancel_requested: 検索の中断要求シグナル（引数なし）。
    """

    # シグナル
    search_requested = Signal(dict)  # 検索条件を渡す
    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = get_config()
        self._extension_popup: ExtensionPopup | None = None
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI 構築
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """ウィジェットの UI を構築する。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        layout.addWidget(self._create_folder_group())
        layout.addWidget(self._create_condition_group())
        layout.addWidget(self._create_regex_group())

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
        layout.addStretch()

    def _create_folder_group(self) -> QGroupBox:
        """検索対象フォルダグループを構築して返す。

        Returns:
            フォルダパス入力と参照ボタンを含む :class:`QGroupBox`。
        """
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
        """検索条件グループを構築して返す。

        Returns:
            キーワード・除外語・拡張子フィルタを含む :class:`QGroupBox`。
        """
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
        self._extension_edit.setPlaceholderText("例: txt,md,docx")
        self._extension_edit.setText(",".join(self._config.target_extensions))
        ext_layout.addWidget(self._extension_edit)

        self._ext_btn = QPushButton("▼")
        self._ext_btn.setFixedWidth(30)
        self._ext_btn.clicked.connect(self._show_extension_popup)
        ext_layout.addWidget(self._ext_btn)

        layout.addLayout(ext_layout)

        return group

    def _create_regex_group(self) -> QGroupBox:
        """正規表現オプショングループを構築して返す。

        Returns:
            チェックオプションとパターン挿入ボタンを含む :class:`QGroupBox`。
        """
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

        # 挿入ボタン
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

    # ------------------------------------------------------------------
    # 公開 API
    # ------------------------------------------------------------------

    def set_searching(self, searching: bool) -> None:
        """検索中かどうかに応じてボタンの有効/無効を切り替える。

        Args:
            searching: ``True`` の場合、検索ボタンを無効化し中断ボタンを有効化する。
        """
        self._search_btn.setEnabled(not searching)
        self._cancel_btn.setEnabled(searching)

    def update_available_extensions(self, extensions: list[str]) -> None:
        """拡張子ポップアップに利用可能な拡張子を通知する（フォルダ走査後）。

        Args:
            extensions: 利用可能な拡張子のリスト。
        """
        if self._extension_popup:
            self._extension_popup.set_available(extensions)

    def get_search_folder(self) -> str:
        """検索フォルダのパスを返す。

        Returns:
            フォルダパス入力フィールドの現在値。
        """
        return self._folder_edit.text()

    def set_search_folder(self, folder: str) -> None:
        """検索フォルダのパスを設定する。

        Args:
            folder: 設定するフォルダパス文字列。
        """
        self._folder_edit.setText(folder)

    # ------------------------------------------------------------------
    # プライベートスロット
    # ------------------------------------------------------------------

    def _on_browse_folder(self) -> None:
        """参照ボタンクリック時にフォルダ選択ダイアログを開く。"""
        folder = QFileDialog.getExistingDirectory(
            self,
            "検索対象フォルダを選択",
            self._folder_edit.text() or str(Path.home()),
        )
        if folder:
            self._folder_edit.setText(folder)

    def _show_extension_popup(self) -> None:
        """拡張子選択ポップアップを表示する。

        初回呼び出し時にポップアップを生成して :attr:`extensions_selected`
        シグナルを接続する。現在のテキストフィールドの値を選択状態に反映する。
        """
        if self._extension_popup is None:
            self._extension_popup = ExtensionPopup(self)
            self._extension_popup.extensions_selected.connect(
                self._on_extensions_selected
            )

        # 現在の選択をポップアップに反映（テキストフィールドの値をドット付きに正規化）
        current_raw = [
            ext.strip()
            for ext in self._extension_edit.text().split(",")
            if ext.strip()
        ]
        # ドットなしで入力されている場合でも照合できるよう、ドット付きで揃える
        current = [
            ext if ext.startswith(".") else f".{ext}"
            for ext in current_raw
        ]
        self._extension_popup.set_selected(current)

        # ボタンの下に表示
        pos = self._ext_btn.mapToGlobal(self._ext_btn.rect().bottomLeft())
        self._extension_popup.move(pos)
        self._extension_popup.show()

    def _on_extensions_selected(self, extensions: list[str]) -> None:
        """ポップアップで拡張子が選択されたとき、テキストフィールドに反映する。

        :class:`ExtensionPopup` はドット付き（例: ``".docx"``）で拡張子を
        返すため、ここでドットを除去してからフィールドにセットする。

        Args:
            extensions: ポップアップから受け取ったドット付き拡張子のリスト。
        """
        stripped = [ext.lstrip(".") for ext in extensions]
        self._extension_edit.setText(",".join(stripped))

    def _insert_pattern(self, pattern: str) -> None:
        """カーソル位置に正規表現パターンを挿入する。

        カッコ付きパターン（``"()"`` や ``"(?:)"`` など）の場合は、
        カーソルをカッコの内側に移動する。正規表現モードを自動でオンにする。

        Args:
            pattern: 挿入する正規表現パターン文字列。
        """
        cursor = self._keyword_edit.cursorPosition()
        current = self._keyword_edit.text()

        new_text = current[:cursor] + pattern + current[cursor:]
        self._keyword_edit.setText(new_text)

        # カッコ付きパターンの場合は中にカーソルを置く
        if pattern.endswith("()"):
            self._keyword_edit.setCursorPosition(cursor + len(pattern) - 1)
        else:
            self._keyword_edit.setCursorPosition(cursor + len(pattern))

        # 正規表現モードをオンに
        self._regex_check.setChecked(True)
        self._keyword_edit.setFocus()

    def _show_regex_help(self) -> None:
        """正規表現ヘルプダイアログを表示する。"""
        dialog = RegexHelpDialog(self)
        dialog.exec()

    def _on_search_clicked(self) -> None:
        """検索ボタンクリック時に検索条件を収集して :attr:`search_requested` を発行する。

        拡張子フィールドの値はドットを除去してから渡す。
        """
        conditions = {
            "folder": self._folder_edit.text(),
            "keyword": self._keyword_edit.text(),
            "is_regex": self._regex_check.isChecked(),
            "exclude_keywords": [
                kw.strip()
                for kw in self._exclude_edit.text().split(",")
                if kw.strip()
            ],
            # ドットを除去して FileEnumerator が期待する形式（例: "docx"）に統一
            "extensions": [
                ext.strip().lstrip(".")
                for ext in self._extension_edit.text().split(",")
                if ext.strip()
            ],
            "ignore_case": self._ignore_case_check.isChecked(),
            "multiline": self._multiline_check.isChecked(),
            "dotall": self._dotall_check.isChecked(),
        }

        self.search_requested.emit(conditions)

    def _on_cancel_clicked(self) -> None:
        """中断ボタンクリック時に :attr:`cancel_requested` を発行する。"""
        self.cancel_requested.emit()
