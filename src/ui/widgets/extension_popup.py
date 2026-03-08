"""拡張子選択ポップアップ。

プリセット拡張子とフォルダ内で検出された拡張子をチェックボックスで
表示し、選択結果を :attr:`ExtensionPopup.extensions_selected` シグナルで
通知する。
"""

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
    """拡張子選択ポップアップ。

    プリセット拡張子とフォルダ内で利用可能な拡張子を一覧表示し、
    ユーザーが選択した拡張子リストを :attr:`extensions_selected` シグナルで
    通知する。ポップアップウィンドウとして表示される。

    Signals:
        extensions_selected: 選択された拡張子のリスト（``list[str]``）を持つ
            シグナル。OK ボタンクリック時に発行される。
    """

    extensions_selected = Signal(list)

    # 定義済み拡張子（カテゴリ別）。ドット付きで表示用として保持する。
    # SearchPanel 側でドットを除去してから FileEnumerator に渡すこと。
    PRESET_EXTENSIONS: dict[str, list[str]] = {
        "Office": [".docx", ".xlsx", ".pptx"],
        "PDF": [".pdf"],
        "テキスト": [".txt", ".md", ".log"],
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self._config = get_config()
        self._checkboxes: dict[str, QCheckBox] = {}
        self._available: list[str] = []
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI 構築
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """ウィジェットの UI を構築する。"""
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

    # ------------------------------------------------------------------
    # 公開 API
    # ------------------------------------------------------------------

    def set_available(self, extensions: list[str]) -> None:
        """フォルダ内で利用可能な拡張子を動的セクションに設定する。

        プリセット拡張子と重複する拡張子は追加しない。
        既存の動的チェックボックスはいったん削除してから再構築する。

        Args:
            extensions: 利用可能な拡張子のリスト（ドット付き、例: ``[".txt"]``）。
        """
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
                    cb,
                )
        else:
            self._dynamic_label.hide()

    def set_selected(self, extensions: list[str]) -> None:
        """チェックボックスの選択状態を外部から設定する。

        Args:
            extensions: チェックを入れる拡張子のリスト。
                リストに含まれない拡張子はチェックを外す。
        """
        for ext, cb in self._checkboxes.items():
            cb.setChecked(ext in extensions)

    def get_selected(self) -> list[str]:
        """現在チェックされている拡張子のリストを返す。

        Returns:
            チェック済み拡張子のリスト（ドット付き、例: ``[".docx", ".pdf"]``）。
        """
        return [ext for ext, cb in self._checkboxes.items() if cb.isChecked()]

    # ------------------------------------------------------------------
    # プライベートヘルパー
    # ------------------------------------------------------------------

    def _get_preset_extensions(self) -> list[str]:
        """プリセット拡張子の全リストを返す。

        Returns:
            :attr:`PRESET_EXTENSIONS` の全値を結合したリスト。
        """
        result: list[str] = []
        for extensions in self.PRESET_EXTENSIONS.values():
            result.extend(extensions)
        return result

    # ------------------------------------------------------------------
    # プライベートスロット
    # ------------------------------------------------------------------

    def _apply_filter(self, text: str) -> None:
        """フィルタ入力に応じてチェックボックスの表示/非表示を切り替える。

        Args:
            text: フィルタ文字列（大文字小文字を区別しない部分一致）。
        """
        text = text.lower()
        for ext, cb in self._checkboxes.items():
            cb.setVisible(text in ext.lower())

    def _select_all(self) -> None:
        """現在表示されているすべてのチェックボックスをオンにする。"""
        for cb in self._checkboxes.values():
            if cb.isVisible():
                cb.setChecked(True)

    def _select_none(self) -> None:
        """現在表示されているすべてのチェックボックスをオフにする。"""
        for cb in self._checkboxes.values():
            if cb.isVisible():
                cb.setChecked(False)

    def _on_ok(self) -> None:
        """OK ボタンクリック時に選択結果を通知してポップアップを閉じる。"""
        self.extensions_selected.emit(self.get_selected())
        self.hide()
