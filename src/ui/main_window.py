"""メインウィンドウ"""

from collections import Counter
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QRunnable, Qt, QThread, QThreadPool, Signal, Slot
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow, QMessageBox, QSplitter, QVBoxLayout, QWidget

from src.common.config import get_config
from src.common.logger import get_logger
from src.common.utils import format_file_size
from src.enumeration import FileEnumerator, FileInfo
from src.extraction import get_supported_extensions
from src.preview import RenderedPreview, build_preview
from src.preview.converter import OFFICE_EXTENSIONS, available_backends, prune_preview_cache
from src.preview.loader import BACKEND_NAMES
from src.preview.scheme import PreviewStore
from src.search import (
    CompiledQuery,
    QueryError,
    Searcher,
    SearchOptions,
    SearchSummary,
    shutdown_pool,
)
from src.ui import icons
from src.ui.platform import style_title_bar
from src.ui.settings import UserSettings, apply_to_config
from src.ui.theme import theme
from src.ui.widgets import (
    AboutDialog,
    PreviewPanel,
    RegexHelpDialog,
    ResultsPanel,
    SearchBar,
    SettingsDialog,
    ShortcutsDialog,
    StatusBar,
)
from src.ui.widgets.results_panel import Entry


# ---------------------------------------------------------------------------
# バックグラウンド処理
# ---------------------------------------------------------------------------

class SearchWorker(QObject):
    """検索ワーカー（専用スレッドで動く）"""
    
    status_changed = Signal(str)
    progress_updated = Signal(int, int, int, int)  # 処理済みbytes, 総bytes, 処理済み件数, 総件数
    result_found = Signal(object)  # SearchResult
    finished = Signal(object)  # SearchSummary
    failed = Signal(str)
    
    def __init__(self, folder: Path, options: SearchOptions, extensions: set[str],
                 include_subfolders: bool, max_matches: int):
        super().__init__()
        self._folder = folder
        self._options = options
        self._extensions = extensions
        self._include_subfolders = include_subfolders
        self._max_matches = max_matches
        self._enumerator = FileEnumerator()
        self._searcher = Searcher()
        self._cancelled = False
    
    def cancel(self) -> None:
        self._cancelled = True
        self._enumerator.cancel()
        self._searcher.cancel()
    
    @Slot()
    def run(self) -> None:
        try:
            self.status_changed.emit("ファイルを数えています…")
            enumeration = self._enumerator.enumerate(
                self._folder,
                include_subfolders=self._include_subfolders,
                target_extensions=self._extensions,
            )
            if self._cancelled:
                self.finished.emit(SearchSummary(cancelled=True))
                return
            self.status_changed.emit(f"{len(enumeration.files):,} ファイルを検索しています…")
            summary = self._searcher.search_files(
                enumeration.files,
                self._options,
                max_matches=self._max_matches,
                result_callback=self.result_found.emit,
                progress_callback=self.progress_updated.emit,
            )
            summary.cancelled = summary.cancelled or self._cancelled
            self.finished.emit(summary)
        except Exception as e:
            get_logger("search").exception("error", f"Search failed: {e}", e)
            self.failed.emit(str(e) or type(e).__name__)


class _TaskSignals(QObject):
    done = Signal(int, object)


class ListingTask(QRunnable):
    """フォルダ内のファイル一覧を作る（検索前の表示用）"""
    
    def __init__(self, token: int, folder: Path, include_subfolders: bool):
        super().__init__()
        self.setAutoDelete(False)
        self.signals = _TaskSignals()
        self._token = token
        self._folder = folder
        self._include_subfolders = include_subfolders
    
    def run(self) -> None:
        try:
            result = FileEnumerator().enumerate(
                self._folder,
                include_subfolders=self._include_subfolders,
                target_extensions=get_supported_extensions(),
            )
            files = result.files
        except Exception:
            files = []
        self.signals.done.emit(self._token, files)


class PreviewTask(QRunnable):
    """プレビュー生成（変換・描画準備に時間がかかるため別スレッドで行う）"""
    
    def __init__(self, token: int, file_info: FileInfo, options: Optional[SearchOptions], mode: str):
        super().__init__()
        self.setAutoDelete(False)  # Python側で寿命を管理する
        self.signals = _TaskSignals()
        self._token = token
        self._file_info = file_info
        self._options = options
        self._mode = mode
    
    def run(self) -> None:
        try:
            preview = build_preview(self._file_info, self._options, self._mode, PreviewStore.tile_prefix())
        except Exception as e:
            get_logger("preview").exception("error", f"Preview failed: {self._file_info.path}", e)
            preview = RenderedPreview(note=f"プレビューを作成できませんでした: {e}")
        self.signals.done.emit(self._token, preview)


# ---------------------------------------------------------------------------
# ウィンドウ
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """メインウィンドウ"""
    
    def __init__(self, settings: Optional[UserSettings] = None):
        super().__init__()
        self._config = get_config()
        self._logger = get_logger("ui")
        self._settings = settings or UserSettings()
        
        self._search_thread: Optional[QThread] = None
        self._search_worker: Optional[SearchWorker] = None
        self._search_options: Optional[SearchOptions] = None
        self._search_root: Optional[Path] = None
        
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._tasks: dict[int, QRunnable] = {}
        self._preview_token = 0
        self._listing_token = 0
        self._listing_files: list[FileInfo] = []
        self._listing_root: Optional[Path] = None
        self._current_entry: Optional[Entry] = None
        
        self.setAcceptDrops(True)
        self._setup_ui()
        self._setup_shortcuts()
        self._restore_settings()
        self._update_engine_label()
        prune_preview_cache()
        
        theme().changed.connect(self._on_theme_changed)
        self._on_theme_changed(theme().palette)
        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_system_scheme_changed)
        except AttributeError:
            pass
        
        self._logger.info("app_started", "Main window created")
    
    # ------------------------------------------------------------------
    # 構築
    # ------------------------------------------------------------------
    
    def _setup_ui(self) -> None:
        self.setWindowTitle("Unified File Search")
        self.setWindowIcon(icons.app_icon())
        self.setMinimumSize(1080, 680)
        self.resize(1480, 920)
        
        root = QWidget()
        root.setObjectName("AppRoot")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self._search_bar = SearchBar()
        bar = self._search_bar
        bar.search_requested.connect(self._on_search_requested)
        bar.cancel_requested.connect(self._on_cancel_requested)
        bar.folder_changed.connect(self._on_folder_changed)
        bar.types_changed.connect(self._on_types_changed)
        bar.settings_requested.connect(self._open_settings)
        bar.theme_requested.connect(self._set_theme_mode)
        bar.shortcuts_requested.connect(lambda: ShortcutsDialog(self).exec())
        bar.regex_help_requested.connect(lambda: RegexHelpDialog(self).exec())
        bar.about_requested.connect(lambda: AboutDialog(self).exec())
        bar.match_limit_changed.connect(self._on_match_limit_changed)
        layout.addWidget(bar)
        
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 12, 12, 12)
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setHandleWidth(10)
        
        self._results = ResultsPanel()
        self._results.setMinimumWidth(340)
        self._results.file_selected.connect(self._on_entry_selected)
        self._results.back_to_listing.connect(self._show_listing)
        self._results.browse_requested.connect(bar.browse_folder)
        self._splitter.addWidget(self._results)
        
        self._preview = PreviewPanel()
        self._preview.setMinimumWidth(480)
        self._preview.mode_change_requested.connect(self._request_preview)
        self._splitter.addWidget(self._preview)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([460, 1000])
        content_layout.addWidget(self._splitter)
        layout.addWidget(content, 1)
        
        self._status = StatusBar()
        layout.addWidget(self._status)
    
    def _setup_shortcuts(self) -> None:
        bindings = [
            (Qt.Key.Key_Escape, self._on_cancel_requested),
            ("Ctrl+F", self._search_bar.focus_query),
            ("Ctrl+L", self._search_bar.focus_query),
            ("Ctrl+O", self._search_bar.browse_folder),
            ("Ctrl+,", self._open_settings),
            (Qt.Key.Key_F1, lambda: ShortcutsDialog(self).exec()),
            ("Ctrl+E", self._preview.reveal_current),
            ("Ctrl+Shift+C", self._preview.copy_path),
            ("Ctrl+Return", self._preview.open_current),
        ]
        for key, handler in bindings:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(handler)
    
    # ------------------------------------------------------------------
    # 設定の保存・復元
    # ------------------------------------------------------------------
    
    def _restore_settings(self) -> None:
        s = self._settings
        if geometry := s.load_bytes("geometry"):
            self.restoreGeometry(geometry)
        if splitter := s.load_bytes("splitter"):
            self._splitter.restoreState(splitter)
        sort_key = s.load_bytes("sort_key")
        if sort_key:
            self._results.set_sort_key(str(sort_key))
        
        self._search_bar.restore_state(s.search_state)
        self._search_bar.set_match_limit(self._config.search_max_matches_per_file)
        self._search_bar.set_recent_folders(s.recent_folders)
        self._search_bar.set_query_history(s.query_history)
        self._results.set_extension_filter(self._search_bar.selected_extensions())
        if s.last_folder and Path(s.last_folder).is_dir():
            self._search_bar.set_folder(s.last_folder)
        else:
            self._status.set_message("フォルダを選び、検索語を入力して Enter で検索します")
    
    def _save_settings(self) -> None:
        s = self._settings
        s.save_bytes("geometry", self.saveGeometry())
        s.save_bytes("splitter", self._splitter.saveState())
        s.save_bytes("sort_key", self._results.sort_key())
        s.search_state = self._search_bar.state()
        s.sync()
    
    # ------------------------------------------------------------------
    # テーマ
    # ------------------------------------------------------------------
    
    def _set_theme_mode(self, mode: str) -> None:
        self._settings.theme = mode
        theme().mode = mode
        theme().apply()
    
    def _on_system_scheme_changed(self, *_args) -> None:
        if theme().mode == "system":
            theme().apply()
    
    def _on_theme_changed(self, p) -> None:
        icons.refresh_bound()
        self._search_bar.set_theme_mode(theme().mode, p.dark)
        style_title_bar(self, p.dark, p.surface, p.text)
    
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        p = theme().palette
        style_title_bar(self, p.dark, p.surface, p.text)
    
    def _update_engine_label(self) -> None:
        backends = available_backends()
        if backends:
            self._status.set_engine(f"原本表示: {BACKEND_NAMES.get(backends[0], backends[0])}")
            self._status._engine.setToolTip("Office ファイルを開いたときと同じ見た目で表示するための変換エンジン")
        else:
            self._status.set_engine("原本表示: Office ファイルは不可（PDF のみ）")
            self._status._engine.setToolTip(
                "Microsoft Office か LibreOffice をインストールすると、"
                "Excel・Word・PowerPoint も開いたときと同じ見た目で表示できます"
            )
    
    def _on_match_limit_changed(self, value: int) -> None:
        """詳細条件で上限が変えられた（次回以降も使う）"""
        self._settings.match_limit = value
        self._config.search_max_matches_per_file = value
    
    # ------------------------------------------------------------------
    # 設定画面
    # ------------------------------------------------------------------
    
    def _open_settings(self) -> None:
        dialog = SettingsDialog(self._settings, self)
        if dialog.exec():
            apply_to_config(self._settings)
            self._search_bar.set_match_limit(self._config.search_max_matches_per_file)
            theme().mode = self._settings.theme
            theme().use_system_accent = self._settings.use_system_accent
            theme().apply()
            self._update_engine_label()
            shutdown_pool()  # 並列数の変更を反映する
        if dialog.cache_cleared:
            self._status.set_message("キャッシュを消去しました", "check")
    
    # ------------------------------------------------------------------
    # フォルダとファイル一覧（検索前）
    # ------------------------------------------------------------------
    
    def _on_folder_changed(self, folder: str) -> None:
        if self._search_worker is not None:
            return
        path = Path(folder) if folder else None
        valid = path is not None and path.is_dir()
        self._search_bar.set_folder_valid(valid or not folder)
        if not valid:
            self._listing_files = []
            self._listing_root = None
            self._search_bar.set_type_counts(None)
            if folder:
                self._results.show_placeholder("warning", "フォルダが見つかりません", folder)
            else:
                self._results.show_placeholder(
                    "folder-open",
                    "検索するフォルダを選んでください",
                    "上の「参照…」で選ぶか、フォルダをこのウィンドウにドラッグ＆ドロップします。",
                    "フォルダを選ぶ…",
                )
            return
        
        self._listing_token += 1
        token = self._listing_token
        self._results.show_placeholder("folder-open", "ファイルを数えています…")
        task = ListingTask(token, path, self._search_bar.include_subfolders())
        task.signals.done.connect(lambda t, files, p=path: self._on_listing_ready(t, files, p))
        self._tasks[-token] = task
        self._pool.start(task)
    
    def _on_listing_ready(self, token: int, files: list[FileInfo], root: Path) -> None:
        self._tasks.pop(-token, None)
        if token != self._listing_token:
            return
        self._listing_files = files
        self._listing_root = root
        counts = Counter(f.extension for f in files)
        self._search_bar.set_type_counts(dict(counts))
        if not self._results.is_showing_results():
            self._show_listing()
        total = sum(f.size for f in files)
        self._status.set_message(f"{root} — {len(files):,} ファイル（{format_file_size(total)}）", "folder")
    
    def _show_listing(self) -> None:
        if self._listing_root is None:
            return
        self._search_options = None
        self._preview.set_has_query(False)
        self._results.set_listing(self._listing_files, self._listing_root)
        self._results.set_extension_filter(self._search_bar.selected_extensions())
    
    def _on_types_changed(self) -> None:
        self._results.set_extension_filter(self._search_bar.selected_extensions())
    
    # ------------------------------------------------------------------
    # ドラッグ＆ドロップ
    # ------------------------------------------------------------------
    
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
    
    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_dir():
                self._search_bar.set_folder(str(path))
                self._search_bar.focus_query()
                event.acceptProposedAction()
                return
            if path.is_file():
                self._search_bar.set_folder(str(path.parent))
                self._search_bar.focus_query()
                event.acceptProposedAction()
                return
    
    # ------------------------------------------------------------------
    # 検索
    # ------------------------------------------------------------------
    
    def _on_search_requested(self) -> None:
        c = self._search_bar.conditions()
        folder = c["folder"]
        if not folder:
            self._search_bar.browse_folder()
            return
        if not Path(folder).is_dir():
            QMessageBox.warning(self, "フォルダが見つかりません", f"次のフォルダが見つかりません:\n{folder}")
            return
        
        options = SearchOptions(
            query=c["keyword"],
            use_regex=c["use_regex"],
            case_sensitive=c["case_sensitive"],
            ignore_width=c["ignore_width"],
            match_whole=c["match_whole"],
            term_mode=c["term_mode"],
            exclude_words=c["exclude_words"],
            regex_multiline=c["multiline"],
            regex_dot_matches_newline=c["dotall"],
        )
        try:
            CompiledQuery(options)
        except QueryError as e:
            self._status.set_message(str(e), "warning")
            self._search_bar.focus_query()
            return
        
        extensions = set(c["extensions"]) & get_supported_extensions()
        if not extensions:
            self._status.set_message("検索するファイルの種類を1つ以上選んでください", "warning")
            return
        
        self._settings.add_query(options.query)
        self._settings.add_recent_folder(folder)
        self._search_bar.set_query_history(self._settings.query_history)
        self._search_bar.set_recent_folders(self._settings.recent_folders)
        self._start_search(Path(folder), options, extensions, c["include_subfolders"], c["match_limit"])
    
    def _start_search(self, folder: Path, options: SearchOptions, extensions: set[str],
                      include_subfolders: bool, max_matches: int) -> None:
        self._stop_search()
        self._search_options = options
        self._search_root = folder
        self._current_entry = None
        self._preview_token += 1
        self._preview.set_has_query(True)
        
        self._search_bar.set_searching(True)
        self._results.begin_search(folder)
        self._preview.clear()
        self._status.clear_time()
        self._status.show_progress(True)
        self._status.set_indeterminate()
        self._status.set_message("検索しています…", "search")
        
        thread = QThread(self)
        worker = SearchWorker(folder, options, extensions, include_subfolders, max_matches)
        worker.moveToThread(thread)
        worker.status_changed.connect(lambda text: self._status.set_message(text, "search"))
        worker.progress_updated.connect(self._on_progress_updated)
        worker.result_found.connect(self._results.add_result)
        worker.finished.connect(self._on_search_finished)
        worker.failed.connect(self._on_search_failed)
        thread.started.connect(worker.run)
        self._search_thread = thread
        self._search_worker = worker
        thread.start()
        
        self._logger.info("search_started", "Search requested", folder=str(folder),
                          query=options.query, use_regex=options.use_regex)
    
    def _stop_search(self) -> None:
        worker, thread = self._search_worker, self._search_thread
        self._search_worker = None
        self._search_thread = None
        if worker is not None:
            worker.cancel()
            for signal in (worker.status_changed, worker.progress_updated, worker.result_found,
                           worker.finished, worker.failed):
                try:
                    signal.disconnect()
                except (RuntimeError, TypeError):
                    pass
        if thread is not None:
            thread.quit()
            if not thread.wait(5000):
                self._logger.warning("search_stop", "Search thread did not stop in time")
            if worker is not None:
                worker.deleteLater()
            thread.deleteLater()
    
    def _on_cancel_requested(self) -> None:
        if self._search_worker is None:
            return
        self._search_worker.cancel()
        self._status.set_message("中断しています…", "stop")
    
    def _on_progress_updated(self, done_bytes: int, total_bytes: int, done_files: int, total_files: int) -> None:
        percent = int(done_bytes * 100 / total_bytes) if total_bytes else 100
        self._status.set_progress(percent, 100, f"{done_files:,} / {total_files:,} ファイル  {percent}%")
    
    def _on_search_finished(self, summary: SearchSummary) -> None:
        self._stop_search()
        self._search_bar.set_searching(False)
        self._status.show_progress(False)
        self._status.set_time(summary.elapsed)
        self._results.finish_search(summary.cancelled)
        
        if summary.cancelled:
            self._status.set_message("検索を中断しました", "stop")
        elif summary.total_files == 0:
            self._status.set_message("対象のファイルがありません（ファイルの種類とサブフォルダの設定を確認）", "warning")
        else:
            message = (f"{summary.total_files:,} ファイルを検索し、{summary.matched_files:,} ファイルで "
                       f"{summary.total_matches:,} 件見つかりました")
            if summary.error_files:
                message += f"（読み込めないファイル {summary.error_files} 件）"
            self._status.set_message(message, "check")
        self._logger.info("search_completed", "Search completed", files=summary.total_files,
                          matched_files=summary.matched_files, matches=summary.total_matches,
                          cache_hits=summary.cache_hits, elapsed_ms=int(summary.elapsed * 1000))
    
    def _on_search_failed(self, error: str) -> None:
        self._stop_search()
        self._search_bar.set_searching(False)
        self._status.show_progress(False)
        self._results.finish_search(cancelled=True)
        self._status.set_message(f"エラー: {error}", "warning")
        QMessageBox.critical(self, "エラー", f"検索中にエラーが発生しました:\n{error}")
    
    # ------------------------------------------------------------------
    # プレビュー
    # ------------------------------------------------------------------
    
    def _on_entry_selected(self, entry: Entry) -> None:
        if entry is self._current_entry:
            return
        self._current_entry = entry
        self._request_preview("auto")
    
    def _request_preview(self, mode: str) -> None:
        entry = self._current_entry
        if entry is None:
            return
        self._preview_token += 1
        token = self._preview_token
        options = self._search_options if entry.result is not None else None
        converting = mode != "text" and entry.file_info.extension in OFFICE_EXTENSIONS
        self._preview.show_loading(entry.file_info, converting)
        
        task = PreviewTask(token, entry.file_info, options, mode)
        task.signals.done.connect(self._on_preview_ready)
        self._tasks[token] = task
        self._pool.start(task)
    
    def _on_preview_ready(self, token: int, preview: RenderedPreview) -> None:
        self._tasks.pop(token, None)
        if token != self._preview_token or self._current_entry is None:
            if preview.page_document is not None:
                preview.page_document.close()
            return
        self._preview.set_has_query(self._current_entry.result is not None)
        self._preview.set_preview(self._current_entry.file_info, preview)
    
    # ------------------------------------------------------------------
    # 終了
    # ------------------------------------------------------------------
    
    def closeEvent(self, event) -> None:  # noqa: N802
        self._save_settings()
        self._stop_search()
        self._preview_token += 1
        self._listing_token += 1
        self._pool.clear()
        self._pool.waitForDone(3000)
        self._preview.shutdown()
        shutdown_pool()
        self._logger.info("app_closed", "Application closed")
        event.accept()
