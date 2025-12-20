"""ファイル一覧パネル"""

from typing import Optional

from PySide6.QtCore import Qt, Signal
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
from PySide6.QtGui import QAction, QColor


class FileListPanel(QWidget):
    """ファイル一覧パネル"""
    
    # シグナル
    file_selected = Signal(str, int)  # ファイルパス, マッチインデックス
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._setup_ui()
        self._results: list[dict] = []
    
    def _setup_ui(self):
        """UIを構築"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        # ヘッダー
        header_layout = QHBoxLayout()
        
        self._count_label = QLabel("検索結果: 0件")
        header_layout.addWidget(self._count_label)
        
        header_layout.addStretch()
        
        self._status_label = QLabel("")
        header_layout.addWidget(self._status_label)
        
        layout.addLayout(header_layout)
        
        # テーブル
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["ファイル名", "パス", "マッチ数", "位置"])
        
        # ヘッダー設定
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        
        # 選択設定
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        
        # コンテキストメニュー
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        
        # シグナル接続
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.itemDoubleClicked.connect(self._on_item_double_clicked)
        
        layout.addWidget(self._table)
    
    def clear(self):
        """結果をクリア"""
        self._table.setRowCount(0)
        self._results.clear()
        self._count_label.setText("検索結果: 0件")
        self._status_label.setText("")
    
    def set_results(self, results: list[dict]):
        """検索結果を設定
        
        Args:
            results: [
                {
                    "file_path": str,
                    "file_name": str,
                    "match_count": int,
                    "matches": [
                        {"location": str, "text": str, ...}
                    ],
                }
            ]
        """
        self._results = results
        self._table.setRowCount(len(results))
        
        for row, result in enumerate(results):
            # ファイル名
            name_item = QTableWidgetItem(result["file_name"])
            name_item.setToolTip(result["file_path"])
            self._table.setItem(row, 0, name_item)
            
            # パス
            path_item = QTableWidgetItem(result["file_path"])
            self._table.setItem(row, 1, path_item)
            
            # マッチ数
            count_item = QTableWidgetItem(str(result["match_count"]))
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 2, count_item)
            
            # 位置（最初のマッチ）
            if result["matches"]:
                location = result["matches"][0].get("location", "")
                location_item = QTableWidgetItem(location)
            else:
                location_item = QTableWidgetItem("")
            self._table.setItem(row, 3, location_item)
        
        # 件数更新
        total_matches = sum(r["match_count"] for r in results)
        self._count_label.setText(f"検索結果: {len(results)}ファイル ({total_matches}件)")
    
    def set_status(self, text: str, is_warning: bool = False):
        """ステータスを設定"""
        self._status_label.setText(text)
        if is_warning:
            self._status_label.setStyleSheet("color: #ff6600;")
        else:
            self._status_label.setStyleSheet("")
    
    def _on_selection_changed(self):
        """選択変更"""
        rows = self._table.selectionModel().selectedRows()
        if rows:
            row = rows[0].row()
            if 0 <= row < len(self._results):
                result = self._results[row]
                self.file_selected.emit(result["file_path"], 0)
    
    def _on_item_double_clicked(self, item: QTableWidgetItem):
        """ダブルクリック"""
        row = item.row()
        if 0 <= row < len(self._results):
            result = self._results[row]
            # 外部アプリで開く（将来の拡張ポイント）
            pass
    
    def _show_context_menu(self, pos):
        """コンテキストメニューを表示"""
        item = self._table.itemAt(pos)
        if not item:
            return
        
        row = item.row()
        if row < 0 or row >= len(self._results):
            return
        
        result = self._results[row]
        
        menu = QMenu(self)
        
        # パスをコピー
        copy_path_action = QAction("パスをコピー", self)
        copy_path_action.triggered.connect(
            lambda: self._copy_to_clipboard(result["file_path"])
        )
        menu.addAction(copy_path_action)
        
        # ファイル名をコピー
        copy_name_action = QAction("ファイル名をコピー", self)
        copy_name_action.triggered.connect(
            lambda: self._copy_to_clipboard(result["file_name"])
        )
        menu.addAction(copy_name_action)
        
        menu.exec(self._table.mapToGlobal(pos))
    
    def _copy_to_clipboard(self, text: str):
        """クリップボードにコピー"""
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
    
    def get_selected_file(self) -> Optional[str]:
        """選択中のファイルパスを取得"""
        rows = self._table.selectionModel().selectedRows()
        if rows:
            row = rows[0].row()
            if 0 <= row < len(self._results):
                return self._results[row]["file_path"]
        return None
    
    def get_result_at(self, row: int) -> Optional[dict]:
        """指定行の結果を取得"""
        if 0 <= row < len(self._results):
            return self._results[row]
        return None
