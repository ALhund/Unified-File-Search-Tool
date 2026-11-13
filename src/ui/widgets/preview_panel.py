"""プレビューパネル（画面右）"""

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.enumeration import FileInfo
from src.preview import RenderedPreview
from src.ui import icons
from src.ui.platform import file_manager_name, open_file, reveal_in_explorer
from src.ui.theme import theme
from src.ui.widgets.common import (
    ElidedLabel,
    EmptyState,
    InfoBar,
    Segmented,
    card,
    divider,
    ghost_button,
    label,
)
from src.ui.widgets.page_view import PageView
from src.ui.widgets.text_views import PlainTextView, RichTextView

ZOOM_STEPS = [25, 33, 50, 67, 75, 80, 90, 100, 110, 125, 150, 175, 200, 250, 300]
MIN_AUTO_FIT = 50
MAX_MENU_HITS = 300


class _Loading(QWidget):
    """読み込み中の表示"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        self._title = label("読み込んでいます…", "EmptyTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title)
        bar = QProgressBar()
        bar.setRange(0, 0)
        bar.setFixedWidth(220)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(bar)
        row.addStretch(1)
        layout.addLayout(row)
        self._sub = label("", "EmptyText")
        self._sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._sub)
        layout.addStretch(2)
    
    def set_text(self, title: str, sub: str) -> None:
        self._title.setText(title)
        self._sub.setText(sub)
        self._sub.setVisible(bool(sub))


class PreviewPanel(QWidget):
    """プレビューパネル"""
    
    mode_change_requested = Signal(str)  # "auto"（原本表示）/ "text"（テキスト表示）
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._hits: list = []
        self._current_hit = -1
        self._zoom = 100
        self._mode = "rich"
        self._file: Optional[FileInfo] = None
        self._page_document = None
        self._has_query = True
        self._setup_ui()
        theme().changed.connect(self._on_theme_changed)
        self._on_theme_changed(theme().palette)
    
    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame = card()
        outer.addWidget(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # --- 見出し（ファイル名と操作） ---
        header = QHBoxLayout()
        header.setContentsMargins(14, 10, 10, 8)
        header.setSpacing(10)
        self._file_icon = QLabel()
        self._file_icon.setFixedSize(32, 32)
        header.addWidget(self._file_icon)
        
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self._title = ElidedLabel("プレビュー", Qt.TextElideMode.ElideMiddle)
        self._title.setObjectName("PreviewTitle")
        self._path = ElidedLabel("", Qt.TextElideMode.ElideMiddle)
        self._path.setObjectName("Secondary")
        titles.addWidget(self._title)
        titles.addWidget(self._path)
        header.addLayout(titles, 1)
        
        self._mode_switch = Segmented([
            ("auto", "原本", "page", "ファイルを開いたときと同じ見た目で表示 (Ctrl+1)"),
            ("text", "テキスト", "text", "抽出した文字を表示。非表示シートやノートも確認できます (Ctrl+2)"),
        ])
        self._mode_switch.changed.connect(self.mode_change_requested.emit)
        header.addWidget(self._mode_switch)
        header.addWidget(divider())
        
        self._open_btn = ghost_button("external", "アプリで開く (Ctrl+Enter)")
        self._open_btn.clicked.connect(self.open_current)
        self._reveal_btn = ghost_button("folder", f"{file_manager_name()}で表示 (Ctrl+E)")
        self._reveal_btn.clicked.connect(self.reveal_current)
        self._copy_btn = ghost_button("copy", "パスをコピー (Ctrl+Shift+C)")
        self._copy_btn.clicked.connect(self.copy_path)
        for button in (self._open_btn, self._reveal_btn, self._copy_btn):
            header.addWidget(button)
        layout.addLayout(header)
        layout.addWidget(divider(vertical=False))
        
        # --- ツールバー（ジャンプ・ヒット移動・ズーム） ---
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(10, 6, 10, 6)
        toolbar.setSpacing(4)
        
        self._section_icon = QLabel()
        toolbar.addWidget(self._section_icon)
        self._section_combo = QComboBox()
        self._section_combo.setToolTip("ページ・シート・スライドへ移動")
        self._section_combo.setMinimumWidth(170)
        self._section_combo.setMaxVisibleItems(20)
        self._section_combo.activated.connect(self._on_section_chosen)
        toolbar.addWidget(self._section_combo)
        toolbar.addStretch(1)
        
        self._prev_btn = ghost_button("chevron-up", "前のヒット (Shift+F3)")
        self._prev_btn.clicked.connect(self.go_prev_match)
        self._position = QToolButton()
        self._position.setObjectName("Ghost")
        self._position.setToolTip("ヒット箇所の一覧")
        self._position.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._position.setMinimumWidth(84)
        self._position.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hit_menu = QMenu(self._position)
        self._hit_menu.aboutToShow.connect(self._build_hit_menu)
        self._position.setMenu(self._hit_menu)
        self._next_btn = ghost_button("chevron-down", "次のヒット (F3)")
        self._next_btn.clicked.connect(self.go_next_match)
        for widget in (self._prev_btn, self._position, self._next_btn):
            toolbar.addWidget(widget)
        
        toolbar.addSpacing(6)
        toolbar.addWidget(divider())
        toolbar.addSpacing(6)
        
        self._zoom_out_btn = ghost_button("zoom-out", "縮小 (Ctrl+-)")
        self._zoom_out_btn.clicked.connect(lambda: self.step_zoom(-1))
        self._zoom_label = QToolButton()
        self._zoom_label.setObjectName("Ghost")
        self._zoom_label.setToolTip("100% に戻す (Ctrl+0)")
        self._zoom_label.setMinimumWidth(56)
        self._zoom_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._zoom_label.clicked.connect(lambda: self.set_zoom(100))
        self._zoom_in_btn = ghost_button("zoom-in", "拡大 (Ctrl++)")
        self._zoom_in_btn.clicked.connect(lambda: self.step_zoom(1))
        self._fit_btn = ghost_button("fit-width", "幅に合わせる")
        self._fit_btn.clicked.connect(lambda: self.fit_width(shrink_only=False))
        for widget in (self._zoom_out_btn, self._zoom_label, self._zoom_in_btn, self._fit_btn):
            toolbar.addWidget(widget)
        layout.addLayout(toolbar)
        
        # --- 補足メッセージ ---
        self._info_bar = InfoBar()
        info_wrap = QHBoxLayout()
        info_wrap.setContentsMargins(10, 0, 10, 6)
        info_wrap.addWidget(self._info_bar)
        layout.addLayout(info_wrap)
        
        # --- 表示領域 ---
        self._stack = QStackedWidget()
        self._page_view = PageView()
        self._rich_view = RichTextView()
        self._plain_view = PlainTextView()
        for view in (self._page_view, self._rich_view, self._plain_view):
            view.hit_clicked.connect(lambda index: self._goto_hit(index))
            view.zoom_step_requested.connect(self.step_zoom)
            view.section_changed.connect(self._on_section_scrolled)
            view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            view.customContextMenuRequested.connect(lambda pos, v=view: self._show_context_menu(v, pos))
            self._stack.addWidget(view)
        self._loading = _Loading()
        self._stack.addWidget(self._loading)
        self._empty = EmptyState(
            "page",
            "ファイルを選ぶとここに表示されます",
            "ヒットした箇所はマーカーで強調され、<b>F3</b> で次の箇所へ移動できます。",
        )
        self._stack.addWidget(self._empty)
        layout.addWidget(self._stack, 1)
        
        # --- フッター（ファイル情報） ---
        layout.addWidget(divider(vertical=False))
        self._footer = label("", "Tertiary")
        self._footer.setContentsMargins(14, 5, 14, 6)
        self._footer.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._footer)
        
        # ショートカット（プレビュー以外にフォーカスがあっても効くようにウィンドウ単位）
        window_shortcuts = [
            (QKeySequence(Qt.Key.Key_F3), self.go_next_match),
            (QKeySequence("Shift+F3"), self.go_prev_match),
            (QKeySequence("Ctrl+="), lambda: self.step_zoom(1)),
            (QKeySequence("Ctrl++"), lambda: self.step_zoom(1)),
            (QKeySequence("Ctrl+-"), lambda: self.step_zoom(-1)),
            (QKeySequence("Ctrl+0"), lambda: self.set_zoom(100)),
            (QKeySequence("Ctrl+1"), lambda: self._request_mode("auto")),
            (QKeySequence("Ctrl+2"), lambda: self._request_mode("text")),
        ]
        for sequence, handler in window_shortcuts:
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(handler)
        
        self._set_file_controls_enabled(False)
        self._update_position()
        self._update_zoom_label()
        self._stack.setCurrentWidget(self._empty)
    
    # ------------------------------------------------------------------
    # テーマ
    # ------------------------------------------------------------------
    
    def _on_theme_changed(self, p) -> None:
        self._section_icon.setPixmap(icons.pixmap("layers", p.text_secondary, 16))
        self._page_view.apply_theme()
        self._rich_view.apply_theme()
        self._plain_view.apply_theme()
        if self._file is not None:
            self._file_icon.setPixmap(icons.file_pixmap(self._file.extension, 32))
    
    # ------------------------------------------------------------------
    # 内容の設定
    # ------------------------------------------------------------------
    
    def _view(self):
        return {"page": self._page_view, "plain": self._plain_view}.get(self._mode, self._rich_view)
    
    def _set_file_controls_enabled(self, enabled: bool) -> None:
        for widget in (self._open_btn, self._reveal_btn, self._copy_btn, self._mode_switch):
            widget.setEnabled(enabled)
        for widget in (self._zoom_out_btn, self._zoom_in_btn, self._zoom_label, self._fit_btn, self._section_combo):
            widget.setEnabled(enabled)
    
    def show_loading(self, file_info: FileInfo, converting: bool) -> None:
        """読み込み中の表示"""
        self._set_header(file_info)
        self._set_file_controls_enabled(False)
        self._open_btn.setEnabled(True)
        self._reveal_btn.setEnabled(True)
        self._copy_btn.setEnabled(True)
        self._hits = []
        self._current_hit = -1
        self._update_position()
        self._info_bar.hide()
        self._section_combo.clear()
        self._loading.set_text(
            "読み込んでいます…",
            "初回は表示用の変換に数秒かかることがあります" if converting else "",
        )
        self._stack.setCurrentWidget(self._loading)
    
    def _set_header(self, file_info: FileInfo) -> None:
        self._file = file_info
        self._title.setText(file_info.name)
        self._path.setText(str(file_info.path.parent))
        self._file_icon.setPixmap(icons.file_pixmap(file_info.extension, 32))
    
    def set_preview(
        self,
        file_info: FileInfo,
        preview: RenderedPreview,
        start_hit: int = 0,
        expected_hits: Optional[int] = None,
    ) -> None:
        """生成済みのプレビューを表示する
        
        expected_hits: 検索結果の件数（原本表示で見つかった数が少ない場合に案内する）
        """
        self._set_header(file_info)
        self._release_document()
        self._mode = preview.mode
        self._hits = preview.hits
        self._current_hit = -1
        
        self._set_file_controls_enabled(True)
        self._mode_switch.set_item_enabled("auto", preview.page_mode_available)
        self._mode_switch.set_value("auto" if preview.mode == "page" else "text")
        self._fit_btn.setEnabled(preview.mode == "page")
        
        self._section_combo.clear()
        self._section_combo.addItems(preview.sections)
        self._section_combo.setEnabled(len(preview.sections) > 1)
        if not preview.sections:
            self._section_combo.addItem("—")
        
        notes = [preview.note] if preview.note else []
        if preview.truncated:
            notes.append(f"ヒットが多いため、先頭 {len(self._hits):,} 件のみ強調表示しています。")
        if not self._hits and not preview.note and self._has_query:
            notes.append(
                "この表示ではヒット箇所が見つかりませんでした。非表示のシートやノートなどにある場合は「テキスト」表示で確認できます。"
                if preview.mode == "page" else "ヒット箇所はありません。"
            )
        elif (
            preview.mode == "page" and expected_hits and not preview.truncated
            and 0 < len(self._hits) < expected_hits
        ):
            notes.append(
                f"検索結果は {expected_hits:,} 件ですが、原本の表示上で見つかったのは {len(self._hits):,} 件です。"
                "残りはノート・非表示のシートなど画面に表示されない場所にある可能性があります（「テキスト」表示で確認できます）。"
            )
        self._info_bar.show_message(" ".join(notes))
        footer = preview.info
        if preview.encoding:
            footer = f"{footer}  |  文字コード: {preview.encoding}" if footer else f"文字コード: {preview.encoding}"
        self._footer.setText(footer)
        
        view = self._view()
        if preview.mode == "page":
            self._page_document = preview.page_document
            self._page_view.set_document(preview.page_document, preview.page_hits)
        elif preview.mode == "plain":
            self._plain_view.set_content(preview.plain_text, preview.plain_hits)
        else:
            self._rich_view.set_content(preview.html)
        self._stack.setCurrentWidget(view)
        
        # ページ表示は幅に合わせる（縮小のみ）、テキストは 100%
        if preview.mode == "page":
            self.fit_width(shrink_only=True)
        else:
            self.set_zoom(100)
        if self._hits:
            self._goto_hit(min(start_hit, len(self._hits) - 1))
        self._update_position()
    
    def set_has_query(self, has_query: bool) -> None:
        self._has_query = has_query
    
    def _release_document(self) -> None:
        self._page_view.clear()
        if self._page_document is not None:
            self._page_document.close()
            self._page_document = None
    
    def clear(self) -> None:
        self._release_document()
        self._file = None
        self._hits = []
        self._current_hit = -1
        self._title.setText("プレビュー")
        self._path.setText("")
        self._file_icon.clear()
        self._footer.setText("")
        self._section_combo.clear()
        self._info_bar.hide()
        self._set_file_controls_enabled(False)
        self._update_position()
        self._stack.setCurrentWidget(self._empty)
    
    def shutdown(self) -> None:
        self._page_view.shutdown()
        self._release_document()
    
    def current_file(self) -> Optional[FileInfo]:
        return self._file
    
    # ------------------------------------------------------------------
    # ヒット箇所の移動
    # ------------------------------------------------------------------
    
    def _update_position(self) -> None:
        total = len(self._hits)
        if total == 0:
            self._position.setText("ヒットなし")
        else:
            current = self._current_hit + 1 if self._current_hit >= 0 else 0
            self._position.setText(f"{current} / {total:,}")
        for widget in (self._prev_btn, self._next_btn, self._position):
            widget.setEnabled(total > 0)
    
    def _goto_hit(self, index: int) -> None:
        if not self._hits:
            return
        self._current_hit = index % len(self._hits)
        self._update_position()
        self._view().goto_hit(self._current_hit)
    
    def go_next_match(self) -> None:
        if self._hits:
            self._goto_hit(self._current_hit + 1)
    
    def go_prev_match(self) -> None:
        if self._hits:
            self._goto_hit(self._current_hit - 1 if self._current_hit >= 0 else -1)
    
    def _build_hit_menu(self) -> None:
        self._hit_menu.clear()
        for index, hit in enumerate(self._hits[:MAX_MENU_HITS]):
            text = f"{index + 1}.  [{hit.label}]  {hit.text}"
            if len(text) > 90:
                text = text[:89] + "…"
            action = self._hit_menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(index == self._current_hit)
            action.triggered.connect(lambda _=False, i=index: self._goto_hit(i))
        if len(self._hits) > MAX_MENU_HITS:
            more = self._hit_menu.addAction(f"…ほか {len(self._hits) - MAX_MENU_HITS:,} 件（F3 で順に移動できます）")
            more.setEnabled(False)
    
    def _on_section_chosen(self, index: int) -> None:
        self._view().goto_section(index)
    
    def _on_section_scrolled(self, index: int) -> None:
        if 0 <= index < self._section_combo.count():
            self._section_combo.blockSignals(True)
            self._section_combo.setCurrentIndex(index)
            self._section_combo.blockSignals(False)
    
    def _request_mode(self, mode: str) -> None:
        button = self._mode_switch.button(mode)
        if self._file is not None and button is not None and button.isEnabled():
            self._mode_switch.set_value(mode)
            self.mode_change_requested.emit(mode)
    
    # ------------------------------------------------------------------
    # ズーム
    # ------------------------------------------------------------------
    
    def set_zoom(self, value: int) -> None:
        self._zoom = max(ZOOM_STEPS[0], min(ZOOM_STEPS[-1], int(value)))
        self._view().set_zoom(self._zoom / 100)
        self._update_zoom_label()
    
    def step_zoom(self, direction: int) -> None:
        if self._file is None:
            return
        if direction > 0:
            target = next((z for z in ZOOM_STEPS if z > self._zoom), ZOOM_STEPS[-1])
        else:
            target = next((z for z in reversed(ZOOM_STEPS) if z < self._zoom), ZOOM_STEPS[0])
        self.set_zoom(target)
    
    def _update_zoom_label(self) -> None:
        self._zoom_label.setText(f"{self._zoom}%")
    
    def fit_width(self, shrink_only: bool = False) -> None:
        """ページの幅を表示領域に合わせる"""
        width = self._page_view.content_width()
        if not width or self._mode != "page":
            return
        available = self._page_view.viewport().width() - 48  # 余白の分
        value = int(available / width * 100)
        if shrink_only:
            value = min(100, max(MIN_AUTO_FIT, value))
        self.set_zoom(value)
    
    # ------------------------------------------------------------------
    # ファイル操作
    # ------------------------------------------------------------------
    
    def open_current(self) -> None:
        if self._file is not None:
            open_file(self._file.path)
    
    def reveal_current(self) -> None:
        if self._file is not None:
            reveal_in_explorer(self._file.path)
    
    def copy_path(self) -> None:
        if self._file is not None:
            QGuiApplication.clipboard().setText(str(self._file.path))
    
    def _show_context_menu(self, view, pos) -> None:
        menu = QMenu(self)
        if view is not self._page_view:
            menu.addAction(icons.icon("copy"), "コピー\tCtrl+C", view.copy)
            menu.addAction("すべて選択\tCtrl+A", view.selectAll)
        if self._file is not None:
            if not menu.isEmpty():
                menu.addSeparator()
            menu.addAction(icons.icon("external"), "アプリで開く", self.open_current)
            menu.addAction(icons.icon("folder"), f"{file_manager_name()}で表示", self.reveal_current)
        menu.exec(view.mapToGlobal(pos))
