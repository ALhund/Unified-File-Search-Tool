"""プレビューパネル"""

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QSlider,
    QApplication,
    QMenu,
    QSplitter,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtGui import QAction


class PreviewPanel(QWidget):
    """プレビューパネル"""
    
    # シグナル
    match_selected = Signal(int)  # マッチインデックス
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._current_html: str = ""
        self._matches: list[dict] = []
        self._zoom_level: int = 100
        self._setup_ui()
    
    def _setup_ui(self):
        """UIを構築"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        # ツールバー
        toolbar = QHBoxLayout()
        
        # マッチ箇所プルダウン
        toolbar.addWidget(QLabel("マッチ箇所:"))
        
        self._match_combo = QComboBox()
        self._match_combo.setMinimumWidth(200)
        self._match_combo.currentIndexChanged.connect(self._on_match_changed)
        toolbar.addWidget(self._match_combo)
        
        # 前へ/次へボタン
        self._prev_btn = QPushButton("◀")
        self._prev_btn.setFixedWidth(30)
        self._prev_btn.clicked.connect(self._go_prev_match)
        toolbar.addWidget(self._prev_btn)
        
        self._next_btn = QPushButton("▶")
        self._next_btn.setFixedWidth(30)
        self._next_btn.clicked.connect(self._go_next_match)
        toolbar.addWidget(self._next_btn)
        
        toolbar.addStretch()
        
        # ズーム
        toolbar.addWidget(QLabel("ズーム:"))
        
        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setRange(50, 200)
        self._zoom_slider.setValue(100)
        self._zoom_slider.setFixedWidth(100)
        self._zoom_slider.valueChanged.connect(self._on_zoom_changed)
        toolbar.addWidget(self._zoom_slider)
        
        self._zoom_label = QLabel("100%")
        self._zoom_label.setFixedWidth(40)
        toolbar.addWidget(self._zoom_label)
        
        self._zoom_reset_btn = QPushButton("リセット")
        self._zoom_reset_btn.clicked.connect(self._reset_zoom)
        toolbar.addWidget(self._zoom_reset_btn)
        
        layout.addLayout(toolbar)
        
        # WebEngineView（プレビュー表示）
        self._web_view = QWebEngineView()
        self._web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._web_view.customContextMenuRequested.connect(self._show_context_menu)
        
        # 初期コンテンツ
        self._show_placeholder()
        
        layout.addWidget(self._web_view)
        
        # ファイル情報
        self._info_label = QLabel("")
        self._info_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self._info_label)
    
    def _show_placeholder(self):
        """プレースホルダーを表示"""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    height: 100vh;
                    margin: 0;
                    color: #999;
                    font-family: 'Segoe UI', sans-serif;
                }
            </style>
        </head>
        <body>
            <div>ファイルを選択するとプレビューが表示されます</div>
        </body>
        </html>
        """
        self._web_view.setHtml(html)
    
    def set_content(
        self,
        html: str,
        matches: list[dict],
        file_info: str = "",
    ):
        """コンテンツを設定
        
        Args:
            html: 表示するHTML
            matches: マッチ情報のリスト
            file_info: ファイル情報（下部に表示）
        """
        self._current_html = html
        self._matches = matches
        
        # マッチプルダウン更新
        self._match_combo.clear()
        for i, match in enumerate(matches):
            location = match.get("location", f"マッチ {i+1}")
            text_preview = match.get("text", "")[:30]
            if len(match.get("text", "")) > 30:
                text_preview += "..."
            self._match_combo.addItem(f"{location}: {text_preview}")
        
        # HTML表示
        self._web_view.setHtml(html)
        self._apply_zoom()
        
        # ファイル情報
        self._info_label.setText(file_info)
    
    def clear(self):
        """クリア"""
        self._current_html = ""
        self._matches.clear()
        self._match_combo.clear()
        self._info_label.setText("")
        self._show_placeholder()
    
    def _on_match_changed(self, index: int):
        """マッチ選択変更"""
        if index >= 0:
            self.match_selected.emit(index)
            self._scroll_to_match(index)
    
    def _go_prev_match(self):
        """前のマッチへ"""
        current = self._match_combo.currentIndex()
        if current > 0:
            self._match_combo.setCurrentIndex(current - 1)
    
    def _go_next_match(self):
        """次のマッチへ"""
        current = self._match_combo.currentIndex()
        if current < self._match_combo.count() - 1:
            self._match_combo.setCurrentIndex(current + 1)
    
    def _scroll_to_match(self, index: int):
        """マッチ箇所にスクロール"""
        # JavaScriptでハイライト要素にスクロール
        js = f"""
        var highlights = document.querySelectorAll('.match-highlight');
        if (highlights.length > {index}) {{
            highlights[{index}].scrollIntoView({{behavior: 'smooth', block: 'center'}});
        }}
        """
        self._web_view.page().runJavaScript(js)
    
    def _on_zoom_changed(self, value: int):
        """ズーム変更"""
        self._zoom_level = value
        self._zoom_label.setText(f"{value}%")
        self._apply_zoom()
    
    def _apply_zoom(self):
        """ズームを適用"""
        self._web_view.setZoomFactor(self._zoom_level / 100.0)
    
    def _reset_zoom(self):
        """ズームリセット"""
        self._zoom_slider.setValue(100)
    
    def _show_context_menu(self, pos):
        """コンテキストメニュー"""
        menu = QMenu(self)
        
        # コピー
        copy_action = QAction("コピー", self)
        copy_action.triggered.connect(self._copy_selection)
        menu.addAction(copy_action)
        
        # すべて選択
        select_all_action = QAction("すべて選択", self)
        select_all_action.triggered.connect(self._select_all)
        menu.addAction(select_all_action)
        
        menu.exec(self._web_view.mapToGlobal(pos))
    
    def _copy_selection(self):
        """選択範囲をコピー"""
        self._web_view.page().triggerAction(
            self._web_view.page().WebAction.Copy
        )
    
    def _select_all(self):
        """すべて選択"""
        self._web_view.page().triggerAction(
            self._web_view.page().WebAction.SelectAll
        )
    
    def get_match_count(self) -> int:
        """マッチ数を取得"""
        return len(self._matches)
    
    def select_match(self, index: int):
        """マッチを選択"""
        if 0 <= index < self._match_combo.count():
            self._match_combo.setCurrentIndex(index)
