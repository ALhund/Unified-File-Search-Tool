"""メインウィンドウ"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QObject, QRunnable, QThread, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QSplitter,
    QMessageBox,
)

from src.common.config import get_config
from src.common.logger import get_logger
from src.common.utils import format_file_size
from src.enumeration import FileEnumerator, FileInfo
from src.extraction import get_supported_extensions
from src.preview import RenderedPreview, build_preview
from src.preview.converter import available_backends, prune_preview_cache
from src.preview.loader import BACKEND_NAMES
from src.preview.scheme import PreviewStore
from src.search import (
    CompiledQuery,
    QueryError,
    Searcher,
    SearchOptions,
    SearchResult,
    SearchSummary,
    shutdown_pool,
)
from src.ui.widgets import (
    SearchPanel,
    FileListPanel,
    PreviewPanel,
    StatusBar,
)


class SearchWorker(QObject):
    """検索ワーカー（バックグラウンドスレッドで動く）"""
    
    status_changed = Signal(str)
    progress_updated = Signal(int, int, int, int)  # 処理済みbytes, 総bytes, 処理済み件数, 総件数
    result_found = Signal(object)  # SearchResult
    finished = Signal(object)  # SearchSummary
    failed = Signal(str)
    
    def __init__(
        self,
        folder: Path,
        options: SearchOptions,
        extensions: set[str],
        include_subfolders: bool,
    ):
        super().__init__()
        self._folder = folder
        self._options = options
        self._extensions = extensions
        self._include_subfolders = include_subfolders
        self._enumerator = FileEnumerator()
        self._searcher = Searcher()
        self._cancelled = False
    
    def cancel(self):
        """キャンセル（UIスレッドから呼ばれる）"""
        self._cancelled = True
        self._enumerator.cancel()
        self._searcher.cancel()
    
    @Slot()
    def run(self):
        """検索を実行"""
        try:
            self.status_changed.emit("ファイルを列挙中...")
            enumeration = self._enumerator.enumerate(
                self._folder,
                include_subfolders=self._include_subfolders,
                target_extensions=self._extensions,
            )
            if self._cancelled:
                self.finished.emit(SearchSummary(cancelled=True))
                return
            
            self.status_changed.emit(f"{len(enumeration.files)} ファイルを検索中...")
            summary = self._searcher.search_files(
                enumeration.files,
                self._options,
                result_callback=self.result_found.emit,
                progress_callback=self.progress_updated.emit,
            )
            summary.cancelled = summary.cancelled or self._cancelled
            self.finished.emit(summary)
        
        except Exception as e:
            get_logger("search").exception("error", f"Search failed: {e}", e)
            self.failed.emit(str(e) or type(e).__name__)


class _PreviewSignals(QObject):
    done = Signal(int, object)  # リクエスト番号, RenderedPreview


class PreviewTask(QRunnable):
    """プレビュー生成（変換・描画準備に時間がかかるため別スレッドで行う）"""
    
    def __init__(
        self,
        token: int,
        file_info: FileInfo,
        options: Optional[SearchOptions],
        mode: str,
    ):
        super().__init__()
        self.setAutoDelete(False)  # Python側で寿命を管理する
        self.signals = _PreviewSignals()
        self._token = token
        self._file_info = file_info
        self._options = options
        self._mode = mode
    
    def run(self):
        try:
            preview = build_preview(
                self._file_info, self._options, self._mode, PreviewStore.tile_prefix()
            )
        except Exception as e:
            get_logger("preview").exception("error", f"Preview failed: {self._file_info.path}", e)
            preview = RenderedPreview(note=f"プレビューを生成できませんでした: {e}")
        self.signals.done.emit(self._token, preview)


class MainWindow(QMainWindow):
    """メインウィンドウ"""
    
    def __init__(self):
        super().__init__()
        self._config = get_config()
        self._logger = get_logger("ui")
        
        self._search_thread: Optional[QThread] = None
        self._search_worker: Optional[SearchWorker] = None
        self._search_options: Optional[SearchOptions] = None
        
        # プレビューは最後に要求されたものだけを表示する
        self._preview_token = 0
        self._preview_pool = QThreadPool(self)
        self._preview_pool.setMaxThreadCount(1)
        self._preview_tasks: dict[int, PreviewTask] = {}
        self._current_result: Optional[SearchResult] = None
        
        self._setup_ui()
        self._setup_shortcuts()
        self._show_converter_status()
        prune_preview_cache()
        
        self._logger.info("app_started", "Main window created")
    
    def _setup_ui(self):
        """UIを構築"""
        self.setWindowTitle("Unified File Search Tool")
        self.setMinimumSize(1100, 720)
        self.resize(1440, 900)
        
        central = QWidget()
        self.setCentralWidget(central)
        
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 4)
        main_layout.setSpacing(6)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        
        # 左ペイン: 検索条件 + 結果一覧
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        
        self._search_panel = SearchPanel()
        self._search_panel.search_requested.connect(self._on_search_requested)
        self._search_panel.cancel_requested.connect(self._on_cancel_requested)
        left_layout.addWidget(self._search_panel)
        
        self._file_list_panel = FileListPanel()
        self._file_list_panel.file_selected.connect(self._on_file_selected)
        left_layout.addWidget(self._file_list_panel, 1)
        
        splitter.addWidget(left_widget)
        
        # 右ペイン: プレビュー
        self._preview_panel = PreviewPanel()
        self._preview_panel.mode_change_requested.connect(self._on_preview_mode_requested)
        self._preview_panel.open_requested.connect(self._open_current_file)
        splitter.addWidget(self._preview_panel)
        
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([520, 920])
        main_layout.addWidget(splitter, 1)
        
        self._status_bar = StatusBar()
        main_layout.addWidget(self._status_bar)
    
    def _setup_shortcuts(self):
        """ショートカットを設定"""
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self._on_cancel_requested)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self._search_panel.focus_keyword)
    
    def _show_converter_status(self):
        """原本表示に使う変換エンジンの有無を知らせる"""
        backends = available_backends()
        if backends:
            name = BACKEND_NAMES.get(backends[0], backends[0])
            self._status_bar.set_message(f"準備完了（Officeファイルの原本表示: {name} を使用）")
        else:
            self._status_bar.set_message(
                "準備完了（Microsoft Office / LibreOffice が見つからないため、"
                "Officeファイルはテキスト表示になります）"
            )
    
    # ------------------------------------------------------------------
    # 検索
    # ------------------------------------------------------------------
    
    def _on_search_requested(self, conditions: dict):
        """検索リクエスト"""
        folder = conditions.get("folder", "")
        if not folder:
            QMessageBox.warning(self, "確認", "検索対象フォルダを選択してください。")
            return
        if not Path(folder).is_dir():
            QMessageBox.warning(self, "確認", "指定されたフォルダが存在しません。")
            return
        
        options = SearchOptions(
            query=conditions.get("keyword", ""),
            use_regex=conditions.get("use_regex", False),
            case_sensitive=conditions.get("case_sensitive", False),
            ignore_width=conditions.get("ignore_width", True),
            match_whole=conditions.get("match_whole", False),
            term_mode=conditions.get("term_mode", "and"),
            exclude_words=conditions.get("exclude_words", []),
            regex_multiline=conditions.get("multiline", False),
            regex_dot_matches_newline=conditions.get("dotall", False),
        )
        try:
            CompiledQuery(options)  # 検索前に条件の誤りを知らせる
        except QueryError as e:
            QMessageBox.warning(self, "確認", str(e))
            return
        
        requested = set(conditions.get("extensions") or self._config.target_extensions)
        extensions = requested & get_supported_extensions()
        if not extensions:
            QMessageBox.warning(
                self,
                "確認",
                "検索できる拡張子が指定されていません。\n対応形式: "
                + ", ".join(sorted(get_supported_extensions())),
            )
            return
        
        self._start_search(
            Path(folder), options, extensions, conditions.get("include_subfolders", True)
        )
    
    def _start_search(
        self,
        folder: Path,
        options: SearchOptions,
        extensions: set[str],
        include_subfolders: bool,
    ):
        """検索を開始"""
        self._stop_search()
        
        self._search_options = options
        self._current_result = None
        self._preview_token += 1  # 生成中のプレビューは破棄する
        
        self._search_panel.set_searching(True)
        self._file_list_panel.clear()
        self._preview_panel.clear()
        self._status_bar.clear_time()
        self._status_bar.show_progress(True)
        self._status_bar.set_indeterminate(True)
        self._status_bar.set_message("検索中...")
        
        thread = QThread(self)
        worker = SearchWorker(folder, options, extensions, include_subfolders)
        worker.moveToThread(thread)
        
        worker.status_changed.connect(self._status_bar.set_message)
        worker.progress_updated.connect(self._on_progress_updated)
        worker.result_found.connect(self._on_result_found)
        worker.finished.connect(self._on_search_finished)
        worker.failed.connect(self._on_search_failed)
        thread.started.connect(worker.run)
        
        self._search_thread = thread
        self._search_worker = worker
        thread.start()
        
        self._logger.info(
            "search_started",
            "Search requested",
            folder=str(folder),
            query=options.query,
            use_regex=options.use_regex,
        )
    
    def _stop_search(self):
        """実行中の検索を止めて後始末する"""
        worker, thread = self._search_worker, self._search_thread
        self._search_worker = None
        self._search_thread = None
        
        if worker is not None:
            worker.cancel()
            # 止めた検索の結果が後から届いても無視する
            for signal in (
                worker.status_changed, worker.progress_updated, worker.result_found,
                worker.finished, worker.failed,
            ):
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
    
    def _on_cancel_requested(self):
        """キャンセルリクエスト"""
        if self._search_worker is None:
            return
        self._search_worker.cancel()
        self._status_bar.set_message("中断しています...")
    
    def _on_progress_updated(self, done_bytes: int, total_bytes: int, done_files: int, total_files: int):
        """進捗更新（総ファイルサイズに対する割合）"""
        self._status_bar.set_indeterminate(False)
        percent = int(done_bytes * 100 / total_bytes) if total_bytes else 100
        self._status_bar.set_progress(
            percent,
            100,
            f"{done_files}/{total_files} ファイル  "
            f"{format_file_size(done_bytes)} / {format_file_size(total_bytes)}",
        )
    
    def _on_result_found(self, result: SearchResult):
        """1ファイル分の結果を一覧へ追加（検索中も逐次表示）"""
        self._file_list_panel.add_result(result)
    
    def _on_search_finished(self, summary: SearchSummary):
        """検索完了"""
        self._stop_search()
        self._search_panel.set_searching(False)
        self._status_bar.show_progress(False)
        self._status_bar.set_time(summary.elapsed)
        
        if summary.cancelled:
            message = "検索を中断しました"
        elif summary.total_files == 0:
            message = "対象のファイルが見つかりませんでした"
        else:
            message = (
                f"検索完了: {summary.total_files}ファイル中 {summary.matched_files}ファイルに"
                f" {summary.total_matches}件"
            )
        if summary.error_files:
            message += f"（読み込みエラー {summary.error_files}件）"
        self._status_bar.set_message(message)
        
        limit = self._config.search_max_matches_per_file
        self._file_list_panel.set_status(
            f"件数の「{limit}>」は{limit}件で打ち切ったファイルです" if summary.matched_files else ""
        )
        
        self._logger.info(
            "search_completed",
            message,
            files=summary.total_files,
            matched_files=summary.matched_files,
            matches=summary.total_matches,
            cache_hits=summary.cache_hits,
            elapsed_ms=int(summary.elapsed * 1000),
        )
    
    def _on_search_failed(self, error: str):
        """検索エラー"""
        self._stop_search()
        self._search_panel.set_searching(False)
        self._status_bar.show_progress(False)
        self._status_bar.set_message(f"エラー: {error}")
        QMessageBox.critical(self, "エラー", f"検索中にエラーが発生しました:\n{error}")
    
    # ------------------------------------------------------------------
    # プレビュー
    # ------------------------------------------------------------------
    
    def _on_file_selected(self, result: SearchResult):
        """一覧でファイルが選択された"""
        if result is self._current_result:
            return
        self._current_result = result
        self._request_preview("auto")
    
    def _on_preview_mode_requested(self, mode: str):
        """原本表示/テキスト表示の切り替え"""
        if self._current_result is not None:
            self._request_preview(mode)
    
    def _request_preview(self, mode: str):
        result = self._current_result
        if result is None:
            return
        
        self._preview_token += 1
        token = self._preview_token
        self._preview_panel.show_loading(result.file_info.name)
        
        task = PreviewTask(token, result.file_info, self._search_options, mode)
        task.signals.done.connect(self._on_preview_ready)
        self._preview_tasks[token] = task  # 完了までシグナル元を保持する
        self._preview_pool.start(task)
    
    def _on_preview_ready(self, token: int, preview: RenderedPreview):
        """プレビュー生成完了"""
        self._preview_tasks.pop(token, None)
        if token != self._preview_token:
            # 待っている間に別のファイルが選択された
            if preview.page_document is not None:
                preview.page_document.close()
            return
        self._preview_panel.set_preview(preview)
    
    def _open_current_file(self):
        """選択中のファイルをOS既定のアプリで開く"""
        if self._current_result is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._current_result.file_info.path)))
    
    def closeEvent(self, event):
        """ウィンドウ閉じイベント"""
        self._stop_search()
        self._preview_token += 1
        self._preview_pool.clear()
        self._preview_pool.waitForDone(3000)
        self._preview_panel.shutdown()
        shutdown_pool()
        self._logger.info("app_closed", "Application closed")
        event.accept()
