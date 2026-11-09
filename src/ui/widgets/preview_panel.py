"""プレビューパネル"""

import html
from typing import Optional

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QSlider,
    QMenu,
    QButtonGroup,
)

from src.preview import RenderedPreview
from src.preview.scheme import PreviewSchemeHandler, PreviewStore, SCHEME

MESSAGE_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body {{ display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0;
       color: #888; background: #f3f4f6; font-family: 'Segoe UI', 'Yu Gothic UI', 'Meiryo', sans-serif; }}
</style></head><body><div>{message}</div></body></html>"""


class PreviewPanel(QWidget):
    """プレビューパネル"""
    
    # シグナル
    mode_change_requested = Signal(str)  # "auto"（原本表示）/ "text"（テキスト表示）
    open_requested = Signal()  # 既定のアプリで開く
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._hit_count = 0
        self._zoom_level = 100
        self._pending_hit: Optional[int] = None
        self._loaded = False
        self._doc_id: Optional[str] = None
        
        self._store = PreviewStore()
        self._setup_ui()
        
        # ufst:// スキームでプレビューを配信する
        self._scheme_handler = PreviewSchemeHandler(self._store, self)
        self._web_view.page().profile().installUrlSchemeHandler(SCHEME, self._scheme_handler)
    
    @property
    def store(self) -> PreviewStore:
        return self._store
    
    def _setup_ui(self):
        """UIを構築"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        # --- 1段目: マッチ箇所の移動 ---
        nav = QHBoxLayout()
        nav.addWidget(QLabel("マッチ箇所:"))
        
        self._match_combo = QComboBox()
        self._match_combo.setMinimumWidth(240)
        self._match_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._match_combo.setMaxVisibleItems(25)
        self._match_combo.currentIndexChanged.connect(self._on_match_changed)
        nav.addWidget(self._match_combo, 1)
        
        self._prev_btn = QPushButton("◀ 前")
        self._prev_btn.setToolTip("前のマッチ箇所 (Shift+F3)")
        self._prev_btn.clicked.connect(self.go_prev_match)
        nav.addWidget(self._prev_btn)
        
        self._next_btn = QPushButton("次 ▶")
        self._next_btn.setToolTip("次のマッチ箇所 (F3)")
        self._next_btn.clicked.connect(self.go_next_match)
        nav.addWidget(self._next_btn)
        
        self._position_label = QLabel("0 / 0")
        self._position_label.setMinimumWidth(70)
        self._position_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav.addWidget(self._position_label)
        layout.addLayout(nav)
        
        # --- 2段目: 表示方法とズーム ---
        tools = QHBoxLayout()
        
        self._page_mode_btn = QPushButton("原本表示")
        self._page_mode_btn.setCheckable(True)
        self._page_mode_btn.setToolTip("ファイルを開いたときと同じ見た目で表示します（図形・グラフ・画像を含む）")
        self._text_mode_btn = QPushButton("テキスト表示")
        self._text_mode_btn.setCheckable(True)
        self._text_mode_btn.setToolTip("抽出したテキストを表示します（非表示シートやノートなども確認できます）")
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self._page_mode_btn)
        self._mode_group.addButton(self._text_mode_btn)
        self._page_mode_btn.clicked.connect(lambda: self.mode_change_requested.emit("auto"))
        self._text_mode_btn.clicked.connect(lambda: self.mode_change_requested.emit("text"))
        tools.addWidget(self._page_mode_btn)
        tools.addWidget(self._text_mode_btn)
        
        self._open_btn = QPushButton("アプリで開く")
        self._open_btn.setToolTip("OS既定のアプリケーションでファイルを開きます")
        self._open_btn.clicked.connect(self.open_requested.emit)
        tools.addWidget(self._open_btn)
        
        tools.addStretch()
        
        self._fit_btn = QPushButton("幅に合わせる")
        self._fit_btn.clicked.connect(self._fit_width)
        tools.addWidget(self._fit_btn)
        
        tools.addWidget(QLabel("ズーム:"))
        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setRange(25, 300)
        self._zoom_slider.setValue(100)
        self._zoom_slider.setFixedWidth(120)
        self._zoom_slider.valueChanged.connect(self._on_zoom_changed)
        tools.addWidget(self._zoom_slider)
        
        self._zoom_label = QLabel("100%")
        self._zoom_label.setFixedWidth(44)
        tools.addWidget(self._zoom_label)
        
        self._zoom_reset_btn = QPushButton("100%")
        self._zoom_reset_btn.setToolTip("等倍に戻す")
        self._zoom_reset_btn.clicked.connect(lambda: self._zoom_slider.setValue(100))
        tools.addWidget(self._zoom_reset_btn)
        layout.addLayout(tools)
        
        # --- 補足メッセージ（変換できなかった理由など） ---
        self._note_label = QLabel("")
        self._note_label.setWordWrap(True)
        self._note_label.setStyleSheet(
            "background: #fff4ce; color: #5c4400; border: 1px solid #f0d58c;"
            "border-radius: 3px; padding: 4px 8px;"
        )
        self._note_label.hide()
        layout.addWidget(self._note_label)
        
        # --- 表示領域 ---
        self._web_view = QWebEngineView()
        self._web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._web_view.customContextMenuRequested.connect(self._show_context_menu)
        self._web_view.loadFinished.connect(self._on_load_finished)
        self._web_view.titleChanged.connect(self._on_title_changed)
        layout.addWidget(self._web_view, 1)
        
        # --- ファイル情報 ---
        self._info_label = QLabel("")
        self._info_label.setStyleSheet("color: #666; font-size: 11px;")
        self._info_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._info_label)
        
        # ショートカット
        QShortcut(QKeySequence(Qt.Key.Key_F3), self, activated=self.go_next_match)
        QShortcut(QKeySequence("Shift+F3"), self, activated=self.go_prev_match)
        
        self._set_controls_enabled(False)
        self.show_message("ファイルを選択するとプレビューが表示されます")
    
    def _set_controls_enabled(self, enabled: bool):
        for widget in (
            self._match_combo, self._prev_btn, self._next_btn, self._page_mode_btn,
            self._text_mode_btn, self._open_btn, self._fit_btn,
        ):
            widget.setEnabled(enabled)
    
    # ------------------------------------------------------------------
    # 表示内容の設定
    # ------------------------------------------------------------------
    
    def show_message(self, message: str):
        """メッセージだけを表示（プレースホルダー・読み込み中）"""
        self._loaded = False
        self._web_view.setHtml(MESSAGE_HTML.format(message=html.escape(message)))
    
    def show_loading(self, file_name: str):
        """読み込み中の表示"""
        self._set_controls_enabled(False)
        self._note_label.hide()
        self.show_message(f"{file_name} を読み込み中...")
    
    def set_preview(self, preview: RenderedPreview, start_hit: int = 0):
        """プレビューを表示
        
        Args:
            preview: 生成済みのプレビュー
            start_hit: 最初に移動するマッチ箇所
        """
        doc_id = self._store.new_id()
        self._store.put(doc_id, preview.html, preview.page_document)
        self._doc_id = doc_id
        self._hit_count = len(preview.hits)
        
        # マッチ箇所プルダウン
        self._match_combo.blockSignals(True)
        self._match_combo.clear()
        for index, hit in enumerate(preview.hits, start=1):
            self._match_combo.addItem(f"{index}. [{hit.label}] {hit.text}")
        self._match_combo.blockSignals(False)
        
        self._set_controls_enabled(True)
        has_hits = self._hit_count > 0
        for widget in (self._match_combo, self._prev_btn, self._next_btn):
            widget.setEnabled(has_hits)
        
        # 表示方法ボタン
        self._page_mode_btn.setEnabled(preview.page_mode_available)
        self._page_mode_btn.setChecked(preview.mode == "page")
        self._text_mode_btn.setChecked(preview.mode == "text")
        self._fit_btn.setEnabled(preview.mode == "page")
        
        # 補足
        notes = [preview.note] if preview.note else []
        if preview.truncated:
            notes.append(f"マッチ箇所が多いため、先頭 {self._hit_count} 件のみ強調表示しています")
        if not has_hits and not preview.note:
            notes.append(
                "この表示ではマッチ箇所が見つかりませんでした"
                "（非表示のシートやノートなどに含まれる場合は「テキスト表示」で確認できます）"
                if preview.mode == "page" else "マッチ箇所はありません"
            )
        self._note_label.setText(" / ".join(notes))
        self._note_label.setVisible(bool(notes))
        
        self._info_label.setText(preview.info)
        
        # 読み込み完了後に最初のマッチ箇所へ移動する
        self._pending_hit = min(start_hit, self._hit_count - 1) if has_hits else None
        self._loaded = False
        self._web_view.load(QUrl(self._store.url(doc_id)))
        self._update_position()
    
    def clear(self):
        """クリア"""
        self._doc_id = None
        self._hit_count = 0
        self._pending_hit = None
        self._match_combo.clear()
        self._info_label.setText("")
        self._note_label.hide()
        self._set_controls_enabled(False)
        self._update_position()
        self.show_message("ファイルを選択するとプレビューが表示されます")
        self._store.release_except(None)
    
    def shutdown(self):
        """終了処理"""
        self._scheme_handler.shutdown()
        self._store.release_except(None)
    
    # ------------------------------------------------------------------
    # マッチ箇所の移動
    # ------------------------------------------------------------------
    
    def _on_load_finished(self, ok: bool):
        if not ok or self._doc_id is None:
            return
        if not self._web_view.url().toString().startswith(SCHEME.decode()):
            return
        self._loaded = True
        self._web_view.setZoomFactor(self._zoom_level / 100.0)
        # 表示し終えたので、以前のプレビューを解放する
        self._store.release_except(self._doc_id)
        if self._pending_hit is not None:
            index, self._pending_hit = self._pending_hit, None
            if self._match_combo.currentIndex() == index:
                self._scroll_to_hit(index, smooth=False)
            else:
                self._match_combo.setCurrentIndex(index)
    
    def _on_title_changed(self, title: str):
        """プレビュー内でマッチ箇所がクリックされた（タイトル経由で通知される）"""
        if title.startswith("hit:"):
            try:
                index = int(title.split(":")[1])
            except (IndexError, ValueError):
                return
            if 0 <= index < self._hit_count:
                self._match_combo.setCurrentIndex(index)
    
    def _on_match_changed(self, index: int):
        """マッチ選択変更"""
        self._update_position()
        if index >= 0 and self._loaded:
            self._scroll_to_hit(index)
    
    def _update_position(self):
        current = self._match_combo.currentIndex() + 1 if self._hit_count else 0
        self._position_label.setText(f"{current} / {self._hit_count}")
    
    def go_prev_match(self):
        """前のマッチへ（先頭の次は末尾へ）"""
        if self._hit_count:
            self._match_combo.setCurrentIndex((self._match_combo.currentIndex() - 1) % self._hit_count)
    
    def go_next_match(self):
        """次のマッチへ（末尾の次は先頭へ）"""
        if self._hit_count:
            self._match_combo.setCurrentIndex((self._match_combo.currentIndex() + 1) % self._hit_count)
    
    def _scroll_to_hit(self, index: int, smooth: bool = True):
        """マッチ箇所にスクロールし、現在位置として強調する"""
        self._web_view.page().runJavaScript(
            f"typeof gotoHit === 'function' && gotoHit({int(index)}, {'true' if smooth else 'false'});"
        )
    
    def select_match(self, index: int):
        """マッチを選択"""
        if 0 <= index < self._match_combo.count():
            self._match_combo.setCurrentIndex(index)
    
    def get_match_count(self) -> int:
        """マッチ数を取得"""
        return self._hit_count
    
    # ------------------------------------------------------------------
    # ズーム
    # ------------------------------------------------------------------
    
    def _on_zoom_changed(self, value: int):
        """ズーム変更"""
        self._zoom_level = value
        self._zoom_label.setText(f"{value}%")
        self._web_view.setZoomFactor(value / 100.0)
    
    def _fit_width(self):
        """ページの幅を表示領域に合わせる"""
        def apply(width):
            if not width:
                return
            available = self._web_view.width() - 56  # 余白とスクロールバーの分
            value = int(max(25, min(300, available / float(width) * 100)))
            self._zoom_slider.setValue(value)
        
        self._web_view.page().runJavaScript(
            "typeof contentWidth === 'function' ? contentWidth() : 0;", apply
        )
    
    # ------------------------------------------------------------------
    # コンテキストメニュー
    # ------------------------------------------------------------------
    
    def _show_context_menu(self, pos):
        """コンテキストメニュー"""
        menu = QMenu(self)
        page = self._web_view.page()
        
        copy_action = QAction("コピー", self)
        copy_action.triggered.connect(lambda: page.triggerAction(QWebEnginePage.WebAction.Copy))
        menu.addAction(copy_action)
        
        select_all_action = QAction("すべて選択", self)
        select_all_action.triggered.connect(lambda: page.triggerAction(QWebEnginePage.WebAction.SelectAll))
        menu.addAction(select_all_action)
        
        menu.exec(self._web_view.mapToGlobal(pos))
