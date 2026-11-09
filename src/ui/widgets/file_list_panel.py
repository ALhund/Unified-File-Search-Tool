"""ファイル一覧パネル"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QMenu,
    QApplication,
)

from src.search import SearchResult

COL_NAME, COL_COUNT, COL_LOCATION, COL_FOLDER = range(4)


class _NumericItem(QTableWidgetItem):
    """数値として並べ替えるセル"""
    
    def __lt__(self, other: QTableWidgetItem) -> bool:
        return (self.data(Qt.ItemDataRole.UserRole) or 0) < (other.data(Qt.ItemDataRole.UserRole) or 0)


class FileListPanel(QWidget):
    """ファイル一覧パネル（検索結果）"""
    
    # シグナル
    file_selected = Signal(object)  # SearchResult
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._results: list[SearchResult] = []
        self._total_matches = 0
        self._setup_ui()
    
    def _setup_ui(self):
        """UIを構築"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        header_layout = QHBoxLayout()
        self._count_label = QLabel("検索結果: 0件")
        header_layout.addWidget(self._count_label)
        header_layout.addStretch()
        self._status_label = QLabel("")
        header_layout.addWidget(self._status_label)
        layout.addLayout(header_layout)
        
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["ファイル名", "件数", "最初のマッチ", "フォルダ"])
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(24)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        self._table.setWordWrap(False)
        
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_COUNT, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_LOCATION, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_FOLDER, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(COL_NAME, 200)
        self._table.setColumnWidth(COL_LOCATION, 150)
        
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.itemDoubleClicked.connect(lambda item: self._open_file(self._result_at(item.row())))
        
        layout.addWidget(self._table)
    
    def clear(self):
        """結果をクリア"""
        self._table.setRowCount(0)
        self._results.clear()
        self._total_matches = 0
        self._count_label.setText("検索結果: 0件")
        self._status_label.setText("")
    
    def add_result(self, result: SearchResult):
        """検索結果を1ファイル分追加（検索中に逐次呼ばれる）"""
        index = len(self._results)
        self._results.append(result)
        self._total_matches += result.match_count
        
        # 追加中に並べ替えが走ると行がずれるため一時的に止める
        self._table.setSortingEnabled(False)
        row = self._table.rowCount()
        self._table.insertRow(row)
        
        info = result.file_info
        name_item = QTableWidgetItem(info.name)
        name_item.setData(Qt.ItemDataRole.UserRole, index)
        name_item.setToolTip(str(info.path))
        self._table.setItem(row, COL_NAME, name_item)
        
        count_item = _NumericItem(result.display_count if not result.error else "!")
        count_item.setData(Qt.ItemDataRole.UserRole, result.match_count)
        count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setItem(row, COL_COUNT, count_item)
        
        if result.error:
            location_item = QTableWidgetItem(f"読み込みエラー: {result.error}")
            location_item.setToolTip(result.error)
            for item in (name_item, count_item, location_item):
                item.setForeground(QColor("#b00020"))
        else:
            first = result.matches[0]
            location_item = QTableWidgetItem(first.location)
            location_item.setToolTip(first.snippet)
        self._table.setItem(row, COL_LOCATION, location_item)
        
        folder_item = QTableWidgetItem(str(info.path.parent))
        folder_item.setToolTip(str(info.path))
        self._table.setItem(row, COL_FOLDER, folder_item)
        
        self._table.setSortingEnabled(True)
        self._update_count()
        
        # 最初の結果は自動で選択してプレビューを出す
        if index == 0 and not result.error:
            self._table.selectRow(self._table.row(name_item))
    
    def _update_count(self):
        files = sum(1 for r in self._results if not r.error)
        errors = len(self._results) - files
        text = f"検索結果: {files}ファイル（{self._total_matches}件）"
        if errors:
            text += f" / 読み込みエラー {errors}件"
        self._count_label.setText(text)
    
    def set_status(self, text: str, is_warning: bool = False):
        """ステータスを設定"""
        self._status_label.setText(text)
        self._status_label.setStyleSheet("color: #d35400;" if is_warning else "")
    
    def _result_at(self, row: int) -> Optional[SearchResult]:
        item = self._table.item(row, COL_NAME)
        if item is None:
            return None
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is None or not 0 <= index < len(self._results):
            return None
        return self._results[index]
    
    def _on_selection_changed(self):
        """選択変更"""
        rows = self._table.selectionModel().selectedRows()
        if rows and (result := self._result_at(rows[0].row())):
            self.file_selected.emit(result)
    
    def _show_context_menu(self, pos):
        """コンテキストメニューを表示"""
        item = self._table.itemAt(pos)
        result = self._result_at(item.row()) if item else None
        if result is None:
            return
        
        path = result.file_info.path
        menu = QMenu(self)
        
        actions = [
            ("ファイルを開く", lambda: self._open_file(result)),
            ("フォルダを開く", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))),
            (None, None),
            ("パスをコピー", lambda: QApplication.clipboard().setText(str(path))),
            ("ファイル名をコピー", lambda: QApplication.clipboard().setText(path.name)),
        ]
        for label, handler in actions:
            if label is None:
                menu.addSeparator()
                continue
            action = QAction(label, self)
            action.triggered.connect(handler)
            menu.addAction(action)
        
        menu.exec(self._table.viewport().mapToGlobal(pos))
    
    @staticmethod
    def _open_file(result: Optional[SearchResult]):
        """OS既定のアプリで開く"""
        if result is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(result.file_info.path)))
    
    def get_selected_result(self) -> Optional[SearchResult]:
        """選択中の結果を取得"""
        rows = self._table.selectionModel().selectedRows()
        return self._result_at(rows[0].row()) if rows else None
    
    def get_selected_file(self) -> Optional[Path]:
        """選択中のファイルパスを取得"""
        result = self.get_selected_result()
        return result.file_info.path if result else None
    
    def result_count(self) -> int:
        return len(self._results)
