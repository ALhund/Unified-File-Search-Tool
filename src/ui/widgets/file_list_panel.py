"""ファイル一覧パネル。

検索結果（:class:`SearchResult`）を表形式で表示し、
行選択時に :attr:`file_selected` シグナルを発行する。
右クリックコンテキストメニューでファイル/フォルダを開いたり、
パスをクリップボードにコピーしたりできる。
"""

import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.search.searcher import SearchResult


class FileListPanel(QWidget):
    """ファイル一覧パネル。

    検索結果（SearchResult）を表形式で表示する。
    行選択時に :attr:`file_selected` シグナルを発行する。

    Signals:
        file_selected: ``(file_path: str, match_index: int)`` を持つシグナル。
            行が選択されると発行される。
    """

    # シグナル: ファイルパス, 最初のマッチインデックス
    file_selected = Signal(str, int)

    # テーブル列定義
    _COL_NO = 0
    _COL_NAME = 1
    _COL_EXT = 2
    _COL_PATH = 3
    _COL_COUNT = 4

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._results: list[SearchResult] = []
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI 構築
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """ウィジェットの UI を構築する。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ヘッダー行
        header_layout = QHBoxLayout()
        self._count_label = QLabel("検索結果: 0件")
        header_layout.addWidget(self._count_label)
        header_layout.addStretch()
        self._status_label = QLabel("")
        header_layout.addWidget(self._status_label)
        layout.addLayout(header_layout)

        # テーブル
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["#", "ファイル名", "種別", "パス", "件数"])

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(self._COL_NO, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self._COL_NAME, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self._COL_EXT, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self._COL_PATH, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self._COL_COUNT, QHeaderView.ResizeMode.ResizeToContents)

        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)

        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        layout.addWidget(self._table)

    # ------------------------------------------------------------------
    # 公開 API
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """テーブルと結果リストをクリアする。"""
        self._table.setRowCount(0)
        self._results.clear()
        self._count_label.setText("検索結果: 0件")
        self._status_label.setText("")

    def set_results(self, results: list[SearchResult]) -> None:
        """検索結果をまとめてテーブルにセットする。

        既存の行をすべて置き換える。逐次追加には :meth:`add_result` を使うこと。

        Args:
            results: セットする :class:`SearchResult` のリスト。
        """
        self._results = results
        self._table.setRowCount(len(results))

        for row, result in enumerate(results):
            self._populate_row(row, result)

        self._update_count_label()

    def add_result(self, result: SearchResult) -> None:
        """検索結果をリアルタイムに行追加する（検索中の逐次表示用）。

        :meth:`set_results` を再呼び出しするよりも効率的。

        Args:
            result: 追加する :class:`SearchResult`。
        """
        self._results.append(result)
        row = len(self._results) - 1
        self._table.insertRow(row)
        self._populate_row(row, result)
        self._update_count_label()

    def set_status(self, text: str, is_warning: bool = False) -> None:
        """ステータスラベルにテキストをセットする。

        Args:
            text: 表示するテキスト。
            is_warning: ``True`` の場合、テキストをオレンジ色で表示する。
        """
        self._status_label.setText(text)
        color = "#e65100" if is_warning else ""
        self._status_label.setStyleSheet(f"color:{color};" if color else "")

    def get_selected_file_path(self) -> str | None:
        """選択中の行のファイルパスを返す。

        Returns:
            選択行のファイルパス文字列、未選択の場合は ``None``。
        """
        rows = self._table.selectionModel().selectedRows()
        if rows:
            row = rows[0].row()
            if 0 <= row < len(self._results):
                return str(self._results[row].file_info.path)
        return None

    def get_result_by_path(self, file_path: str) -> SearchResult | None:
        """ファイルパスから一致する :class:`SearchResult` を返す。

        Args:
            file_path: 検索するファイルパス文字列。

        Returns:
            一致する :class:`SearchResult`、見つからない場合は ``None``。
        """
        for result in self._results:
            if str(result.file_info.path) == file_path:
                return result
        return None

    def get_result_at(self, row: int) -> SearchResult | None:
        """行インデックスから :class:`SearchResult` を返す。

        Args:
            row: 取得する行インデックス（0 始まり）。

        Returns:
            該当する :class:`SearchResult`、範囲外の場合は ``None``。
        """
        if 0 <= row < len(self._results):
            return self._results[row]
        return None

    # ------------------------------------------------------------------
    # プライベートヘルパー
    # ------------------------------------------------------------------

    def _populate_row(self, row: int, result: SearchResult) -> None:
        """テーブルの 1 行分のセルを設定する（DRY ヘルパー）。

        :meth:`set_results` と :meth:`add_result` の共通ロジックを集約する。

        Args:
            row: 設定する行インデックス（0 始まり）。
            result: 行に表示する :class:`SearchResult`。
        """
        file_path = str(result.file_info.path)
        file_name = result.file_info.name
        extension = result.file_info.extension
        tooltip = _build_tooltip(result)

        # 通し番号
        no_item = _make_item(str(row + 1), align=Qt.AlignmentFlag.AlignCenter)
        self._table.setItem(row, self._COL_NO, no_item)

        # ファイル名
        name_item = _make_item(file_name)
        name_item.setToolTip(tooltip)
        self._table.setItem(row, self._COL_NAME, name_item)

        # 拡張子バッジ
        ext_item = _make_item(extension.upper(), align=Qt.AlignmentFlag.AlignCenter)
        ext_item.setBackground(QColor(_ext_color(extension)))
        ext_item.setForeground(QColor("#ffffff"))
        ext_item.setFont(_bold_font())
        self._table.setItem(row, self._COL_EXT, ext_item)

        # パス
        path_item = _make_item(file_path)
        path_item.setToolTip(file_path)
        self._table.setItem(row, self._COL_PATH, path_item)

        # マッチ件数（50超 → "50>"）
        count_item = _make_item(result.display_count, align=Qt.AlignmentFlag.AlignCenter)
        if result.truncated:
            count_item.setForeground(QColor("#e65100"))
        self._table.setItem(row, self._COL_COUNT, count_item)

    def _update_count_label(self) -> None:
        """ヘッダーのファイル数・マッチ件数ラベルを更新する。"""
        total = sum(r.match_count for r in self._results)
        self._count_label.setText(
            f"検索結果: {len(self._results)} ファイル（{total} 件）"
        )

    # ------------------------------------------------------------------
    # プライベートスロット
    # ------------------------------------------------------------------

    def _on_selection_changed(self) -> None:
        """行選択が変わったとき、:attr:`file_selected` シグナルを発行する。"""
        rows = self._table.selectionModel().selectedRows()
        if rows:
            row = rows[0].row()
            if 0 <= row < len(self._results):
                file_path = str(self._results[row].file_info.path)
                self.file_selected.emit(file_path, 0)

    def _show_context_menu(self, pos) -> None:
        """右クリックコンテキストメニューを表示する。

        Args:
            pos: メニューを表示する位置（テーブルのローカル座標）。
        """
        item = self._table.itemAt(pos)
        if not item:
            return
        row = item.row()
        if row < 0 or row >= len(self._results):
            return

        result = self._results[row]
        file_path = str(result.file_info.path)
        file_name = result.file_info.name

        menu = QMenu(self)

        open_action = QAction("ファイルを開く", self)
        open_action.triggered.connect(lambda: _open_file(file_path))
        menu.addAction(open_action)

        open_folder_action = QAction("フォルダを開く", self)
        open_folder_action.triggered.connect(
            lambda: _open_file(str(Path(file_path).parent))
        )
        menu.addAction(open_folder_action)

        menu.addSeparator()

        copy_path_action = QAction("パスをコピー", self)
        copy_path_action.triggered.connect(
            lambda: _copy_to_clipboard(file_path)
        )
        menu.addAction(copy_path_action)

        copy_name_action = QAction("ファイル名をコピー", self)
        copy_name_action.triggered.connect(
            lambda: _copy_to_clipboard(file_name)
        )
        menu.addAction(copy_name_action)

        menu.exec(self._table.mapToGlobal(pos))


# ---------------------------------------------------------------------------
# ヘルパー関数（モジュールレベル、UI に依存しないロジック）
# ---------------------------------------------------------------------------

def _make_item(
    text: str,
    align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
) -> QTableWidgetItem:
    """テキストとアライメントを設定した :class:`QTableWidgetItem` を返す。

    Args:
        text: セルに表示するテキスト。
        align: テキストのアライメントフラグ。デフォルトは左揃え・縦中央。

    Returns:
        設定済みの :class:`QTableWidgetItem`。
    """
    item = QTableWidgetItem(text)
    item.setTextAlignment(align)
    return item


def _bold_font() -> QFont:
    """拡張子バッジ用のボールドフォントを返す。

    Returns:
        ポイントサイズ 9 のボールド :class:`QFont`。
    """
    font = QFont()
    font.setBold(True)
    font.setPointSize(9)
    return font


def _ext_color(extension: str) -> str:
    """拡張子に対応するバッジ背景色の16進数カラーコードを返す。

    Args:
        extension: 拡張子文字列（ドットなし、例: ``"docx"``）。

    Returns:
        ``"#RRGGBB"`` 形式のカラーコード。未定義の拡張子はグレー系。
    """
    palette = {
        "docx": "#1565c0",
        "xlsx": "#2e7d32",
        "pptx": "#b71c1c",
        "pdf": "#e65100",
        "md": "#6a1b9a",
        "txt": "#37474f",
        "log": "#4e342e",
    }
    return palette.get(extension.lower(), "#607d8b")


def _build_tooltip(result: SearchResult) -> str:
    """ホバー時に表示するツールチップ文字列を生成する。

    Args:
        result: ツールチップを生成する :class:`SearchResult`。

    Returns:
        パス・サイズ・更新日時・打ち切り情報を改行区切りで結合した文字列。
    """
    parts = [str(result.file_info.path)]
    size_kb = result.file_info.size / 1024
    parts.append(f"サイズ: {size_kb:.1f} KB")
    parts.append(f"更新日時: {result.file_info.modified_time:%Y-%m-%d %H:%M}")
    if result.truncated:
        parts.append("※ 50件で打ち切り")
    return "\n".join(parts)


def _open_file(path: str) -> None:
    """OS のデフォルトアプリでファイルまたはフォルダを開く。

    Windows の ``explorer.exe`` を優先し、失敗時は ``os.startfile`` に
    フォールバックする。

    Args:
        path: 開くファイルまたはフォルダの絶対パス。
    """
    try:
        subprocess.Popen(
            ["explorer", path],
            shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        import os
        os.startfile(path)  # type: ignore[attr-defined]


def _copy_to_clipboard(text: str) -> None:
    """テキストをシステムクリップボードにコピーする。

    Args:
        text: コピーするテキスト文字列。
    """
    clipboard = QApplication.clipboard()
    clipboard.setText(text)
