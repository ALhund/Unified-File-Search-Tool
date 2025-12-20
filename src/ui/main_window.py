"""メインウィンドウ"""

import time
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QMessageBox,
    QApplication,
)
from PySide6.QtGui import QKeySequence, QShortcut

from src.common.config import get_config
from src.common.logger import get_logger
from src.enumeration import FileEnumerator, EnumerationResult
from src.extraction import get_extractor
from src.search import Searcher, SearchOptions
from src.metadata import MetadataReader
from src.preview import PreviewRenderer
from src.ui.widgets import (
    SearchPanel,
    FileListPanel,
    PreviewPanel,
    StatusBar,
)


class SearchWorker(QObject):
    """検索ワーカー（バックグラウンドスレッド用）"""
    
    # シグナル
    progress_updated = Signal(int, int, str)  # current, total, message
    file_processed = Signal(dict)  # 1ファイル処理完了
    search_completed = Signal(list, float, bool)  # results, elapsed, truncated
    error_occurred = Signal(str)
    
    def __init__(self):
        super().__init__()
        self._cancelled = False
        self._config = get_config()
        self._logger = get_logger("search")
    
    def cancel(self):
        """キャンセル"""
        self._cancelled = True
    
    def search(
        self,
        folder: str,
        options: SearchOptions,
        extensions: list[str],
    ):
        """検索を実行"""
        self._cancelled = False
        results: list[dict] = []
        start_time = time.time()
        truncated = False
        
        try:
            # 1. ファイル列挙
            self.progress_updated.emit(0, 0, "ファイルを列挙中...")
            
            enumerator = FileEnumerator()
            enum_result = enumerator.enumerate(
                folder,
                extensions=extensions,
            )
            
            if not enum_result.files:
                self.search_completed.emit([], 0, False)
                return
            
            # 大容量ファイル警告
            large_files = [f for f in enum_result.files if f.is_large]
            if large_files:
                self._logger.warning(
                    "large_files_detected",
                    count=len(large_files),
                    threshold_mb=self._config.large_file_threshold_mb,
                )
            
            # 2. 検索実行
            searcher = Searcher()
            total_files = len(enum_result.files)
            total_matches = 0
            
            for i, file_info in enumerate(enum_result.files):
                if self._cancelled:
                    break
                
                self.progress_updated.emit(
                    i + 1,
                    total_files,
                    f"検索中: {file_info.name}",
                )
                
                try:
                    # テキスト抽出
                    extractor = get_extractor(file_info.extension)
                    if not extractor:
                        continue
                    
                    content = extractor.extract(file_info.path)
                    if not content:
                        continue
                    
                    # 検索
                    search_result = searcher.search(content, options)
                    
                    if search_result.matches:
                        result_dict = {
                            "file_path": file_info.path,
                            "file_name": file_info.name,
                            "match_count": search_result.match_count,
                            "matches": [
                                {
                                    "location": m.get_location_info(),
                                    "text": m.text,
                                    "start": m.start,
                                    "end": m.end,
                                }
                                for m in search_result.matches
                            ],
                            "content": content,
                            "truncated": search_result.truncated,
                        }
                        results.append(result_dict)
                        total_matches += search_result.match_count
                        
                        self.file_processed.emit(result_dict)
                        
                        # 打ち切り判定
                        if total_matches >= self._config.max_matches:
                            truncated = True
                            break
                
                except Exception as e:
                    self._logger.error(
                        "file_search_error",
                        file=file_info.path,
                        error=str(e),
                    )
            
            elapsed = time.time() - start_time
            self.search_completed.emit(results, elapsed, truncated)
            
        except Exception as e:
            self._logger.error("search_error", error=str(e))
            self.error_occurred.emit(str(e))


class MainWindow(QMainWindow):
    """メインウィンドウ"""
    
    def __init__(self):
        super().__init__()
        self._config = get_config()
        self._logger = get_logger("ui")
        self._search_thread: Optional[QThread] = None
        self._search_worker: Optional[SearchWorker] = None
        self._preview_renderer = PreviewRenderer()
        self._metadata_reader = MetadataReader()
        
        self._setup_ui()
        self._setup_shortcuts()
        
        self._logger.info("app_started")
    
    def _setup_ui(self):
        """UIを構築"""
        self.setWindowTitle("Unified File Search Tool")
        self.setMinimumSize(1200, 800)
        
        # セントラルウィジェット
        central = QWidget()
        self.setCentralWidget(central)
        
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)
        
        # メインスプリッター（左右分割）
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左ペイン
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        
        # 検索パネル
        self._search_panel = SearchPanel()
        self._search_panel.search_requested.connect(self._on_search_requested)
        self._search_panel.cancel_requested.connect(self._on_cancel_requested)
        left_layout.addWidget(self._search_panel)
        
        # ファイル一覧パネル
        self._file_list_panel = FileListPanel()
        self._file_list_panel.file_selected.connect(self._on_file_selected)
        left_layout.addWidget(self._file_list_panel)
        
        splitter.addWidget(left_widget)
        
        # 右ペイン（プレビュー）
        self._preview_panel = PreviewPanel()
        splitter.addWidget(self._preview_panel)
        
        # スプリッター比率
        splitter.setSizes([400, 800])
        
        main_layout.addWidget(splitter)
        
        # ステータスバー
        self._status_bar = StatusBar()
        main_layout.addWidget(self._status_bar)
    
    def _setup_shortcuts(self):
        """ショートカットを設定"""
        # ESCで中断
        esc_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        esc_shortcut.activated.connect(self._on_cancel_requested)
    
    def _on_search_requested(self, conditions: dict):
        """検索リクエスト"""
        # 入力検証
        folder = conditions.get("folder", "")
        if not folder:
            QMessageBox.warning(self, "警告", "検索対象フォルダを選択してください。")
            return
        
        if not Path(folder).exists():
            QMessageBox.warning(self, "警告", "指定されたフォルダが存在しません。")
            return
        
        keyword = conditions.get("keyword", "")
        if not keyword:
            QMessageBox.warning(self, "警告", "検索語を入力してください。")
            return
        
        # 検索オプション構築
        options = SearchOptions(
            keyword=keyword,
            is_regex=conditions.get("is_regex", False),
            ignore_case=conditions.get("ignore_case", True),
            multiline=conditions.get("multiline", False),
            dotall=conditions.get("dotall", False),
            exclude_keywords=conditions.get("exclude_keywords", []),
        )
        
        extensions = conditions.get("extensions", self._config.target_extensions)
        
        # 検索開始
        self._start_search(folder, options, extensions)
    
    def _start_search(
        self,
        folder: str,
        options: SearchOptions,
        extensions: list[str],
    ):
        """検索を開始"""
        # 前回の検索を停止
        self._stop_search()
        
        # UI更新
        self._search_panel.set_searching(True)
        self._file_list_panel.clear()
        self._preview_panel.clear()
        self._status_bar.show_progress(True)
        self._status_bar.set_message("検索中...")
        
        # ワーカー作成
        self._search_thread = QThread()
        self._search_worker = SearchWorker()
        self._search_worker.moveToThread(self._search_thread)
        
        # シグナル接続
        self._search_worker.progress_updated.connect(self._on_progress_updated)
        self._search_worker.file_processed.connect(self._on_file_processed)
        self._search_worker.search_completed.connect(self._on_search_completed)
        self._search_worker.error_occurred.connect(self._on_search_error)
        
        # 検索開始
        self._search_thread.started.connect(
            lambda: self._search_worker.search(folder, options, extensions)
        )
        self._search_thread.start()
        
        self._logger.info(
            "search_started",
            folder=folder,
            keyword=options.keyword,
            is_regex=options.is_regex,
        )
    
    def _stop_search(self):
        """検索を停止"""
        if self._search_worker:
            self._search_worker.cancel()
        
        if self._search_thread and self._search_thread.isRunning():
            self._search_thread.quit()
            self._search_thread.wait(1000)
        
        self._search_thread = None
        self._search_worker = None
    
    def _on_cancel_requested(self):
        """キャンセルリクエスト"""
        self._stop_search()
        self._search_panel.set_searching(False)
        self._status_bar.show_progress(False)
        self._status_bar.set_message("検索がキャンセルされました")
        
        self._logger.info("search_cancelled")
    
    def _on_progress_updated(self, current: int, total: int, message: str):
        """進捗更新"""
        if total > 0:
            self._status_bar.set_progress(current, total, f"{current}/{total} ファイル")
        else:
            self._status_bar.set_indeterminate(True)
        
        self._status_bar.set_message(message)
    
    def _on_file_processed(self, result: dict):
        """ファイル処理完了"""
        # 逐次表示（リアルタイム更新）
        pass
    
    def _on_search_completed(
        self,
        results: list[dict],
        elapsed: float,
        truncated: bool,
    ):
        """検索完了"""
        # 検索終了
        self._stop_search()
        
        # UI更新
        self._search_panel.set_searching(False)
        self._status_bar.show_progress(False)
        self._status_bar.set_time(elapsed)
        
        # 結果表示
        self._file_list_panel.set_results(results)
        
        if truncated:
            self._file_list_panel.set_status(
                f"※ 結果が{self._config.max_matches}件で打ち切られました",
                is_warning=True,
            )
            self._status_bar.set_message("検索完了（打ち切り）")
        else:
            total_matches = sum(r["match_count"] for r in results)
            self._status_bar.set_message(
                f"検索完了: {len(results)}ファイル, {total_matches}件のマッチ"
            )
        
        self._logger.info(
            "search_completed",
            files=len(results),
            matches=sum(r["match_count"] for r in results),
            elapsed=elapsed,
            truncated=truncated,
        )
    
    def _on_search_error(self, error: str):
        """検索エラー"""
        self._stop_search()
        self._search_panel.set_searching(False)
        self._status_bar.show_progress(False)
        self._status_bar.set_message(f"エラー: {error}")
        
        QMessageBox.critical(self, "エラー", f"検索中にエラーが発生しました:\n{error}")
        
        self._logger.error("search_error", error=error)
    
    def _on_file_selected(self, file_path: str, match_index: int):
        """ファイル選択"""
        # 結果からコンテンツを取得
        result = None
        for r in self._file_list_panel._results:
            if r["file_path"] == file_path:
                result = r
                break
        
        if not result:
            return
        
        content = result.get("content")
        if not content:
            return
        
        # プレビュー生成
        matches = result.get("matches", [])
        html = self._preview_renderer.render_full(content, [])  # マッチハイライト付き
        
        # メタデータ取得
        metadata = self._metadata_reader.read(file_path)
        file_info = ""
        if metadata:
            parts = []
            if metadata.author:
                parts.append(f"作成者: {metadata.author}")
            if metadata.last_modified_by:
                parts.append(f"最終更新者: {metadata.last_modified_by}")
            if metadata.created:
                parts.append(f"作成日: {metadata.created}")
            if content.encoding:
                parts.append(f"文字コード: {content.encoding}")
            file_info = " | ".join(parts)
        
        # プレビュー表示
        self._preview_panel.set_content(html, matches, file_info)
        
        # マッチ箇所にジャンプ
        if match_index < len(matches):
            self._preview_panel.select_match(match_index)
    
    def closeEvent(self, event):
        """ウィンドウ閉じイベント"""
        self._stop_search()
        self._logger.info("app_closed")
        event.accept()
