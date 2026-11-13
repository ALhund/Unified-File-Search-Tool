"""プレビューパネル（画面右）"""

import html
from typing import Optional

from PySide6.QtCore import QEvent, QObject, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.enumeration import FileInfo
from src.preview import RenderedPreview
from src.preview.scheme import PreviewSchemeHandler, PreviewStore, SCHEME
from src.ui import icons
from src.ui.platform import file_manager_name, open_file, reveal_in_explorer
from src.ui.theme import palette, theme
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

ZOOM_STEPS = [25, 33, 50, 67, 75, 80, 90, 100, 110, 125, 150, 175, 200, 250, 300]
MIN_AUTO_FIT = 50
MAX_MENU_HITS = 300

_MESSAGE_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
html, body {{ height: 100%; margin: 0; }}
body {{ display: flex; flex-direction: column; gap: 14px; align-items: center; justify-content: center;
       color: {text}; background: {bg};
       font-family: 'Segoe UI Variable Text', 'Segoe UI', 'Yu Gothic UI', 'Meiryo', sans-serif; font-size: 14px; }}
.spinner {{ width: 30px; height: 30px; border-radius: 50%;
           border: 3px solid {track}; border-top-color: {accent}; animation: spin 0.8s linear infinite; }}
@keyframes spin {{ to {{ transform: rotate(360deg); }} }}
.sub {{ color: {sub}; font-size: 12px; }}
</style></head><body>{spinner}<div>{message}</div><div class="sub">{sub_message}</div></body></html>"""


class PreviewPanel(QWidget):
    """プレビューパネル"""
    
    mode_change_requested = Signal(str)  # "auto"（原本表示）/ "text"（テキスト表示）
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._hits: list = []
        self._current_hit = -1
        self._zoom = 100
        self._pending_hit: Optional[int] = None
        self._loaded = False
        self._doc_id: Optional[str] = None
        self._mode = "text"
        self._file: Optional[FileInfo] = None
        
        self._store = PreviewStore()
        self._setup_ui()
        
        self._scheme_handler = PreviewSchemeHandler(self._store, self)
        self._web_view.page().profile().installUrlSchemeHandler(SCHEME, self._scheme_handler)
        theme().changed.connect(self._on_theme_changed)
        self._on_theme_changed(theme().palette)
    
    @property
    def store(self) -> PreviewStore:
        return self._store
    
    # ------------------------------------------------------------------
    # 構築
    # ------------------------------------------------------------------
    
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
        self._web_view = QWebEngineView()
        self._web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._web_view.customContextMenuRequested.connect(self._show_context_menu)
        self._web_view.loadFinished.connect(self._on_load_finished)
        self._web_view.titleChanged.connect(self._on_title_changed)
        self._stack.addWidget(self._web_view)
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
        self._store.dark = p.dark
        self._web_view.page().setBackgroundColor(QColor(p.preview_bg))
        self._section_icon.setPixmap(icons.pixmap("layers", p.text_secondary, 16))
        if self._loaded:
            self._web_view.page().runJavaScript(f"typeof setDark === 'function' && setDark({str(p.dark).lower()});")
        if self._file is not None:
            self._file_icon.setPixmap(icons.file_pixmap(self._file.extension, 32))
    
    # ------------------------------------------------------------------
    # 内容の設定
    # ------------------------------------------------------------------
    
    def _set_file_controls_enabled(self, enabled: bool) -> None:
        for widget in (self._open_btn, self._reveal_btn, self._copy_btn, self._mode_switch):
            widget.setEnabled(enabled)
        for widget in (self._zoom_out_btn, self._zoom_in_btn, self._zoom_label, self._fit_btn, self._section_combo):
            widget.setEnabled(enabled)
    
    def _show_message(self, message: str, sub_message: str = "", spinner: bool = False) -> None:
        p = palette()
        self._loaded = False
        self._web_view.setHtml(_MESSAGE_HTML.format(
            text=p.text, sub=p.text_secondary, bg=p.preview_bg, track=p.border, accent=p.accent,
            spinner="<div class='spinner'></div>" if spinner else "",
            message=html.escape(message), sub_message=html.escape(sub_message),
        ))
        self._stack.setCurrentWidget(self._web_view)
    
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
        self._show_message(
            "読み込んでいます…",
            "初回は表示用の変換に数秒かかることがあります" if converting else "",
            spinner=True,
        )
    
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
        doc_id = self._store.new_id()
        self._store.put(doc_id, preview.html, preview.page_document)
        self._doc_id = doc_id
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
        self._footer.setText(preview.info)
        
        # 読み込み完了後に最初のヒット箇所へ移動し、ページ表示は幅に合わせる
        self._pending_hit = min(start_hit, len(self._hits) - 1) if self._hits else None
        self._zoom = 100
        self._loaded = False
        self._web_view.load(QUrl(self._store.url(doc_id)))
        self._update_position()
        self._update_zoom_label()
    
    _has_query = True
    
    def set_has_query(self, has_query: bool) -> None:
        self._has_query = has_query
    
    def clear(self) -> None:
        self._doc_id = None
        self._file = None
        self._hits = []
        self._current_hit = -1
        self._pending_hit = None
        self._title.setText("プレビュー")
        self._path.setText("")
        self._file_icon.clear()
        self._footer.setText("")
        self._section_combo.clear()
        self._info_bar.hide()
        self._set_file_controls_enabled(False)
        self._update_position()
        self._stack.setCurrentWidget(self._empty)
        self._store.release_except(None)
    
    def shutdown(self) -> None:
        self._scheme_handler.shutdown()
        self._store.release_except(None)
    
    def current_file(self) -> Optional[FileInfo]:
        return self._file
    
    # ------------------------------------------------------------------
    # 読み込み完了・ページからの通知
    # ------------------------------------------------------------------
    
    def _on_load_finished(self, ok: bool) -> None:
        if not ok or self._doc_id is None:
            return
        if not self._web_view.url().toString().startswith(SCHEME.decode()):
            return
        self._loaded = True
        self._install_wheel_filter()
        self._web_view.setZoomFactor(self._zoom / 100)
        self._store.release_except(self._doc_id)
        
        def after_fit(_=None):
            if self._pending_hit is not None:
                index, self._pending_hit = self._pending_hit, None
                self._goto_hit(index, smooth=False)
        
        if self._mode == "page":
            self.fit_width(shrink_only=True, then=after_fit)
        else:
            after_fit()
    
    def _on_title_changed(self, title: str) -> None:
        parts = title.split(":")
        if len(parts) < 2:
            return
        try:
            value = int(parts[1])
        except ValueError:
            return
        if parts[0] == "hit" and 0 <= value < len(self._hits):
            self._goto_hit(value, scroll=False)
        elif parts[0] == "sec" and 0 <= value < self._section_combo.count():
            self._section_combo.setCurrentIndex(value)
    
    def _install_wheel_filter(self) -> None:
        """Ctrl+ホイールでのズームを、このパネルのズーム操作として扱う"""
        proxy = self._web_view.focusProxy()
        if proxy is not None and not proxy.property("ufst_wheel_filter"):
            proxy.installEventFilter(self)
            proxy.setProperty("ufst_wheel_filter", True)
    
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Wheel and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.step_zoom(1 if delta > 0 else -1)
            return True
        return super().eventFilter(watched, event)
    
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
    
    def _goto_hit(self, index: int, smooth: bool = True, scroll: bool = True) -> None:
        if not self._hits:
            return
        self._current_hit = index % len(self._hits)
        self._update_position()
        if self._loaded:
            # クリックされた箇所（scroll=False）も「現在の箇所」として強調し直す
            self._web_view.page().runJavaScript(
                f"typeof gotoHit === 'function' && gotoHit({self._current_hit}, {'true' if smooth else 'false'});"
            )
    
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
        if self._loaded:
            self._web_view.page().runJavaScript(f"typeof gotoSection === 'function' && gotoSection({index});")
    
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
        self._web_view.setZoomFactor(self._zoom / 100)
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
    
    def fit_width(self, shrink_only: bool = False, then=None) -> None:
        """ページの幅を表示領域に合わせる"""
        def apply(width):
            if width:
                available = self._web_view.width() - 48  # 余白とスクロールバーの分
                value = int(available / float(width) * 100)
                if shrink_only:
                    value = min(100, max(MIN_AUTO_FIT, value))
                self.set_zoom(value)
            if then:
                then()
        
        self._web_view.page().runJavaScript("typeof contentWidth === 'function' ? contentWidth() : 0;", apply)
    
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
    
    def _show_context_menu(self, pos) -> None:
        page = self._web_view.page()
        menu = QMenu(self)
        menu.addAction(icons.icon("copy"), "コピー\tCtrl+C", lambda: page.triggerAction(QWebEnginePage.WebAction.Copy))
        menu.addAction("すべて選択\tCtrl+A", lambda: page.triggerAction(QWebEnginePage.WebAction.SelectAll))
        if self._file is not None:
            menu.addSeparator()
            menu.addAction(icons.icon("external"), "アプリで開く", self.open_current)
            menu.addAction(icons.icon("folder"), f"{file_manager_name()}で表示", self.reveal_current)
        menu.exec(self._web_view.mapToGlobal(pos))
