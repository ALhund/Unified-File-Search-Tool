"""プレビューパネル。

検索結果ファイルの内容を HTML で表示し、マッチ箇所へのナビゲーションと
ページ / シート / スライドの切り替え UI、ズームスライダーを提供する。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

_PLACEHOLDER_HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {
      display: flex; align-items: center; justify-content: center;
      height: 100vh; margin: 0;
      color: #bbb; font-family: 'Segoe UI', sans-serif; font-size: 15px;
      background: #f4f4f4;
    }
  </style>
</head>
<body>ファイルを選択するとプレビューが表示されます</body>
</html>
"""


class PreviewPanel(QWidget):
    """プレビューパネル。

    検索結果ファイルの内容を HTML で表示し、マッチ箇所に移動する。
    ページ / シート / スライドの切り替え UI と
    ズームスライダーを備える。

    Signals:
        match_selected: マッチインデックス（``int``）を持つシグナル。
            コンボボックスでマッチが変更されると発行される。
        navigation_changed: ページ/シート/スライドの値（``str``）を持つシグナル。
            ナビゲーションコンボボックスが変更されると発行される。
    """

    # シグナル
    match_selected = Signal(int)           # マッチインデックス
    navigation_changed = Signal(str)       # ページ/シート/スライド値（文字列）

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_html: str = ""
        self._matches: list[dict] = []
        self._zoom_level: int = 100
        self._block_nav_signal: bool = False
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI 構築
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """ウィジェットの UI を構築する。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        layout.addLayout(self._build_toolbar())
        layout.addLayout(self._build_nav_bar())
        layout.addWidget(self._build_web_view())

        # ファイル情報ラベル（下部）
        self._info_label = QLabel("")
        self._info_label.setStyleSheet("color:#666; font-size:11px; padding:2px 6px;")
        layout.addWidget(self._info_label)

    def _build_toolbar(self) -> QHBoxLayout:
        """上段ツールバー（マッチ選択 + ズーム）を構築して返す。

        Returns:
            配置済みの :class:`QHBoxLayout`。
        """
        bar = QHBoxLayout()

        bar.addWidget(QLabel("マッチ:"))

        self._match_combo = QComboBox()
        self._match_combo.setMinimumWidth(220)
        self._match_combo.currentIndexChanged.connect(self._on_match_changed)
        bar.addWidget(self._match_combo)

        self._prev_btn = QPushButton("◀")
        self._prev_btn.setFixedWidth(30)
        self._prev_btn.setToolTip("前のマッチ")
        self._prev_btn.clicked.connect(self._go_prev_match)
        bar.addWidget(self._prev_btn)

        self._next_btn = QPushButton("▶")
        self._next_btn.setFixedWidth(30)
        self._next_btn.setToolTip("次のマッチ")
        self._next_btn.clicked.connect(self._go_next_match)
        bar.addWidget(self._next_btn)

        bar.addStretch()

        bar.addWidget(QLabel("ズーム:"))

        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setRange(50, 200)
        self._zoom_slider.setValue(100)
        self._zoom_slider.setFixedWidth(110)
        self._zoom_slider.valueChanged.connect(self._on_zoom_changed)
        bar.addWidget(self._zoom_slider)

        self._zoom_label = QLabel("100%")
        self._zoom_label.setFixedWidth(42)
        bar.addWidget(self._zoom_label)

        reset_btn = QPushButton("リセット")
        reset_btn.clicked.connect(self._reset_zoom)
        bar.addWidget(reset_btn)

        return bar

    def _build_nav_bar(self) -> QHBoxLayout:
        """下段ナビバー（ページ / シート / スライド切り替え）を構築して返す。

        デフォルトは非表示。:meth:`set_navigation` で表示する。

        Returns:
            :attr:`_nav_bar_widget` を含む外側の :class:`QHBoxLayout`。
        """
        bar = QHBoxLayout()

        self._nav_label = QLabel("ページ:")
        bar.addWidget(self._nav_label)

        self._nav_combo = QComboBox()
        self._nav_combo.setMinimumWidth(180)
        self._nav_combo.currentIndexChanged.connect(self._on_nav_changed)
        bar.addWidget(self._nav_combo)

        bar.addStretch()

        self._nav_bar_widget = QWidget()
        self._nav_bar_widget.setLayout(bar)
        self._nav_bar_widget.hide()

        # 外側レイアウトに追加するためダミーを返す
        outer = QHBoxLayout()
        outer.addWidget(self._nav_bar_widget)
        return outer

    def _build_web_view(self) -> QWebEngineView:
        """Web ビューを構築して返す。

        Returns:
            プレースホルダー HTML をセット済みの :class:`QWebEngineView`。
        """
        self._web_view = QWebEngineView()
        self._web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._web_view.customContextMenuRequested.connect(self._show_context_menu)
        self._web_view.setHtml(_PLACEHOLDER_HTML)
        return self._web_view

    # ------------------------------------------------------------------
    # 公開 API
    # ------------------------------------------------------------------

    def set_content(
        self,
        rendered_html: str,
        matches: list[dict],
        file_info: str = "",
    ) -> None:
        """プレビュー HTML とマッチ情報をセットする。

        Args:
            rendered_html: レンダラーが生成した HTML 文字列。
            matches: マッチ情報 dict のリスト（プルダウン表示用）。
                各 dict は ``"location"`` と ``"text"`` キーを持つことを想定。
            file_info: ファイル情報テキスト（下部ラベルに表示）。
        """
        self._current_html = rendered_html
        self._matches = matches

        # マッチプルダウン更新
        self._match_combo.blockSignals(True)
        self._match_combo.clear()
        for i, m in enumerate(matches):
            location = m.get("location", f"マッチ {i + 1}")
            preview = m.get("text", "")[:30]
            if len(m.get("text", "")) > 30:
                preview += "..."
            self._match_combo.addItem(f"{location}: {preview}")
        self._match_combo.blockSignals(False)

        self._web_view.setHtml(rendered_html)
        self._apply_zoom()
        self._info_label.setText(file_info)

    def set_navigation(
        self,
        label: str,
        items: list[str],
        current: str = "",
    ) -> None:
        """ページ / シート / スライド切り替えコンボを設定する。

        Args:
            label: ラベルテキスト（``"ページ:"`` / ``"シート:"`` / ``"スライド:"``）。
            items: 選択肢のリスト。要素数が 1 以下の場合はナビバーを非表示にする。
            current: 現在値（一致する項目が選択される）。
        """
        self._block_nav_signal = True
        try:
            if len(items) <= 1:
                self._nav_bar_widget.hide()
                self._nav_combo.clear()
                return

            self._nav_label.setText(label)
            self._nav_combo.clear()
            self._nav_combo.addItems(items)
            idx = self._nav_combo.findText(current)
            if idx >= 0:
                self._nav_combo.setCurrentIndex(idx)
            self._nav_bar_widget.show()
        finally:
            self._block_nav_signal = False

    def clear(self) -> None:
        """プレビューをクリアしてプレースホルダーを表示する。"""
        self._current_html = ""
        self._matches.clear()
        self._match_combo.clear()
        self._nav_combo.clear()
        self._nav_bar_widget.hide()
        self._info_label.setText("")
        self._web_view.setHtml(_PLACEHOLDER_HTML)

    def get_match_count(self) -> int:
        """現在セットされているマッチ件数を返す。

        Returns:
            マッチ情報リストの長さ。
        """
        return len(self._matches)

    def select_match(self, index: int) -> None:
        """指定インデックスのマッチをコンボボックスで選択する。

        Args:
            index: 選択するマッチインデックス（0 始まり）。範囲外は無視。
        """
        if 0 <= index < self._match_combo.count():
            self._match_combo.setCurrentIndex(index)

    # ------------------------------------------------------------------
    # プライベートスロット
    # ------------------------------------------------------------------

    def _on_match_changed(self, index: int) -> None:
        """マッチコンボボックスの選択が変わったとき呼ばれる。

        :attr:`match_selected` シグナルを発行し、Web ビューをスクロールする。

        Args:
            index: 新しく選択されたインデックス。
        """
        if index >= 0:
            self.match_selected.emit(index)
            self._scroll_to_match(index)

    def _go_prev_match(self) -> None:
        """前のマッチに移動する。"""
        cur = self._match_combo.currentIndex()
        if cur > 0:
            self._match_combo.setCurrentIndex(cur - 1)

    def _go_next_match(self) -> None:
        """次のマッチに移動する。"""
        cur = self._match_combo.currentIndex()
        if cur < self._match_combo.count() - 1:
            self._match_combo.setCurrentIndex(cur + 1)

    def _scroll_to_match(self, index: int) -> None:
        """指定インデックスのマッチ要素に Web ビューをスクロールする。

        Args:
            index: スクロール先のマッチインデックス。
        """
        js = f"""
        var items = document.querySelectorAll('.match-highlight');
        if (items.length > {index}) {{
            items[{index}].scrollIntoView({{behavior:'smooth', block:'center'}});
        }}
        """
        self._web_view.page().runJavaScript(js)

    def _on_nav_changed(self, index: int) -> None:
        """ナビゲーションコンボボックスの選択が変わったとき呼ばれる。

        :attr:`navigation_changed` シグナルを発行する。
        ただし :attr:`_block_nav_signal` が ``True`` のときは何もしない。

        Args:
            index: 新しく選択されたインデックス。
        """
        if self._block_nav_signal or index < 0:
            return
        value = self._nav_combo.itemText(index)
        self.navigation_changed.emit(value)

    def _on_zoom_changed(self, value: int) -> None:
        """ズームスライダーの値が変わったとき呼ばれる。

        Args:
            value: 新しいズーム値（50–200）。
        """
        self._zoom_level = value
        self._zoom_label.setText(f"{value}%")
        self._apply_zoom()

    def _apply_zoom(self) -> None:
        """現在の :attr:`_zoom_level` を Web ビューに適用する。"""
        self._web_view.setZoomFactor(self._zoom_level / 100.0)

    def _reset_zoom(self) -> None:
        """ズームを 100% にリセットする。"""
        self._zoom_slider.setValue(100)

    def _show_context_menu(self, pos) -> None:
        """Web ビューの右クリックコンテキストメニューを表示する。

        Args:
            pos: メニューを表示する位置（Web ビューのローカル座標）。
        """
        menu = QMenu(self)

        copy_action = QAction("コピー", self)
        copy_action.triggered.connect(self._copy_selection)
        menu.addAction(copy_action)

        select_all_action = QAction("すべて選択", self)
        select_all_action.triggered.connect(self._select_all)
        menu.addAction(select_all_action)

        menu.exec(self._web_view.mapToGlobal(pos))

    def _copy_selection(self) -> None:
        """選択中のテキストをクリップボードにコピーする。"""
        self._web_view.page().triggerAction(
            self._web_view.page().WebAction.Copy
        )

    def _select_all(self) -> None:
        """Web ビュー内のすべてのテキストを選択する。"""
        self._web_view.page().triggerAction(
            self._web_view.page().WebAction.SelectAll
        )
