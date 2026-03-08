"""メインウィンドウモジュール。

アプリケーションのメインウィンドウ（:class:`MainWindow`）と
バックグラウンド検索を担う :class:`SearchWorker` を定義する。
"""

import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.common.config import get_config
from src.common.logger import get_logger
from src.enumeration import FileEnumerator
from src.metadata import MetadataReader
from src.metadata.metadata_reader import FileMetadata
from src.preview import PreviewRenderer
from src.search import Searcher, SearchOptions, SearchResult
from src.extraction.base import ExtractedContent
from src.ui.widgets import (
    FileListPanel,
    PreviewPanel,
    SearchPanel,
    StatusBar,
)


# ---------------------------------------------------------------------------
# バックグラウンド検索ワーカー
# ---------------------------------------------------------------------------

class SearchWorker(QObject):
    """バックグラウンドスレッドで動作する検索ワーカー。

    ファイル列挙（:class:`FileEnumerator`）→ ファイルごとの
    :meth:`Searcher.search_file` 呼び出しを順次実行し、
    進捗・結果・エラーをシグナルで通知する。
    UI ロジックは持たず、シグナル発行の責務のみを担う。

    Signals:
        progress_updated (int, int, str): (current, total, message) 進捗通知。
        file_processed (object): マッチが見つかった :class:`SearchResult` の通知。
        search_completed (list, float): (全結果リスト, 経過秒) 完了通知。
        error_occurred (str): 予期しないエラーのメッセージ通知。
    """

    progress_updated = Signal(int, int, str)
    file_processed = Signal(object)
    search_completed = Signal(list, float)
    error_occurred = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._cancelled = False
        self._config = get_config()
        self._logger = get_logger("search")

    def cancel(self) -> None:
        """進行中の検索をキャンセルする。"""
        self._cancelled = True

    def search(
        self,
        folder: str,
        options: SearchOptions,
        extensions: list[str],
    ) -> None:
        """検索を実行する（``QThread.started`` シグナルに接続して呼ぶ）。

        ファイル列挙後、各ファイルを逐次検索し、
        マッチが見つかった都度 :attr:`file_processed` を発行する。
        完了時は :attr:`search_completed` を発行する。

        Args:
            folder: 検索対象フォルダのパス文字列。
            options: 検索オプション。
            extensions: 対象拡張子のリスト（ドットなし小文字）。
        """
        self._cancelled = False
        results: list[SearchResult] = []
        start_time = time.monotonic()

        try:
            self.progress_updated.emit(0, 0, "ファイルを列挙中...")

            enumerator = FileEnumerator()
            enum_result = enumerator.enumerate(
                Path(folder),
                target_extensions=set(extensions),
            )

            if not enum_result.files:
                self.search_completed.emit([], 0.0)
                return

            searcher = Searcher()
            total = len(enum_result.files)

            for i, file_info in enumerate(enum_result.files):
                if self._cancelled:
                    break

                self.progress_updated.emit(
                    i + 1,
                    total,
                    f"検索中: {file_info.name}",
                )

                try:
                    result = searcher.search_file(file_info, options)
                except Exception as exc:
                    self._logger.warning(
                        "skip",
                        f"Failed to search {file_info.path}: {exc}",
                        file_path=str(file_info.path),
                    )
                    continue

                if result.matches:
                    results.append(result)
                    self.file_processed.emit(result)

            elapsed = time.monotonic() - start_time
            self.search_completed.emit(results, elapsed)

        except Exception as exc:
            self._logger.exception("error", f"Search worker failed: {exc}", exc)
            self.error_occurred.emit(str(exc))


# ---------------------------------------------------------------------------
# メインウィンドウ
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """アプリケーションのメインウィンドウ。

    左ペイン（:class:`SearchPanel` + :class:`FileListPanel`）と
    右ペイン（:class:`PreviewPanel`）を水平スプリッターで配置する。
    検索はバックグラウンドスレッド（:class:`SearchWorker`）で実行し、
    結果をリアルタイムにファイルリストへ追加する。
    """

    def __init__(self) -> None:
        super().__init__()
        self._config = get_config()
        self._logger = get_logger("ui")
        self._search_thread: QThread | None = None
        self._search_worker: SearchWorker | None = None
        self._preview_renderer = PreviewRenderer()
        self._metadata_reader = MetadataReader()
        self._current_result: SearchResult | None = None

        self._setup_ui()
        self._setup_shortcuts()
        self._logger.info("app_started", "Application started")

    # ------------------------------------------------------------------
    # UI 構築
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """ウィジェット・レイアウト・シグナル接続を初期化する。"""
        self.setWindowTitle("Unified File Search Tool")
        self.setMinimumSize(1280, 800)

        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 4)
        main_layout.setSpacing(6)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左ペイン
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        self._search_panel = SearchPanel()
        self._search_panel.search_requested.connect(self._on_search_requested)
        self._search_panel.cancel_requested.connect(self._on_cancel_requested)
        left_layout.addWidget(self._search_panel)

        self._file_list_panel = FileListPanel()
        self._file_list_panel.file_selected.connect(self._on_file_selected)
        left_layout.addWidget(self._file_list_panel)

        splitter.addWidget(left_widget)

        # 右ペイン（プレビュー）
        self._preview_panel = PreviewPanel()
        self._preview_panel.navigation_changed.connect(self._on_navigation_changed)
        splitter.addWidget(self._preview_panel)

        splitter.setSizes([420, 860])
        main_layout.addWidget(splitter)

        # ステータスバー
        self._status_bar = StatusBar()
        main_layout.addWidget(self._status_bar)

    def _setup_shortcuts(self) -> None:
        """キーボードショートカットを登録する（ESC = 検索キャンセル）。"""
        esc_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        esc_shortcut.activated.connect(self._on_cancel_requested)

    # ------------------------------------------------------------------
    # 検索フロー
    # ------------------------------------------------------------------

    def _on_search_requested(self, conditions: dict) -> None:
        """SearchPanel から検索要求を受け取り、入力検証後に検索を開始する。

        Args:
            conditions: SearchPanel が発行する検索条件辞書。
        """
        folder = conditions.get("folder", "").strip()
        if not folder:
            QMessageBox.warning(self, "警告", "検索対象フォルダを選択してください。")
            return
        if not Path(folder).is_dir():
            QMessageBox.warning(self, "警告", "指定されたフォルダが存在しません。")
            return

        keyword = conditions.get("keyword", "").strip()
        if not keyword:
            QMessageBox.warning(self, "警告", "検索語を入力してください。")
            return

        options = SearchOptions(
            query=keyword,
            use_regex=conditions.get("is_regex", False),
            case_sensitive=not conditions.get("ignore_case", True),
            regex_ignore_case=conditions.get("ignore_case", True),
            regex_multiline=conditions.get("multiline", False),
            regex_dot_matches_newline=conditions.get("dotall", False),
            exclude_words=conditions.get("exclude_keywords", []),
        )
        extensions: list[str] = conditions.get(
            "extensions", self._config.target_extensions
        )

        self._start_search(folder, options, extensions)

    def _start_search(
        self,
        folder: str,
        options: SearchOptions,
        extensions: list[str],
    ) -> None:
        """バックグラウンドスレッドで検索を開始する。

        前回の検索が実行中の場合は停止してから開始する。

        Args:
            folder: 検索対象フォルダのパス文字列。
            options: 検索オプション。
            extensions: 対象拡張子のリスト（ドットなし小文字）。
        """
        self._stop_search()

        self._search_panel.set_searching(True)
        self._file_list_panel.clear()
        self._preview_panel.clear()
        self._current_result = None
        self._status_bar.show_progress(True)
        self._status_bar.set_message("検索中...")

        self._search_thread = QThread()
        self._search_worker = SearchWorker()
        self._search_worker.moveToThread(self._search_thread)

        self._search_worker.progress_updated.connect(self._on_progress_updated)
        self._search_worker.file_processed.connect(self._on_file_processed)
        self._search_worker.search_completed.connect(self._on_search_completed)
        self._search_worker.error_occurred.connect(self._on_search_error)

        self._search_thread.started.connect(
            lambda: self._search_worker.search(folder, options, extensions)
        )
        self._search_thread.start()

        self._logger.info(
            "search_started",
            f"Search started: '{options.query}'",
            folder=folder,
            use_regex=options.use_regex,
        )

    def _stop_search(self) -> None:
        """進行中の検索スレッドを停止・破棄する。"""
        if self._search_worker:
            self._search_worker.cancel()
        if self._search_thread and self._search_thread.isRunning():
            self._search_thread.quit()
            self._search_thread.wait(2000)
        self._search_thread = None
        self._search_worker = None

    # ------------------------------------------------------------------
    # 検索シグナルスロット
    # ------------------------------------------------------------------

    def _on_cancel_requested(self) -> None:
        """検索のキャンセルを処理する（ESC キーまたはキャンセルボタン）。"""
        self._stop_search()
        self._search_panel.set_searching(False)
        self._status_bar.show_progress(False)
        self._status_bar.set_message("検索をキャンセルしました")
        self._logger.info("search_cancelled", "Search cancelled by user")

    def _on_progress_updated(self, current: int, total: int, message: str) -> None:
        """検索進捗の更新を受け取りステータスバーを更新する。

        Args:
            current: 処理済みファイル数。
            total: 合計ファイル数（0 の場合は不定進捗モード）。
            message: 現在処理中のファイル名などのメッセージ。
        """
        if total > 0:
            self._status_bar.set_progress(
                current, total, f"{current}/{total} ファイル"
            )
        else:
            self._status_bar.set_indeterminate(True)
        self._status_bar.set_message(message)

    def _on_file_processed(self, result: SearchResult) -> None:
        """マッチが見つかったファイルをリアルタイムにファイルリストへ追加する。

        Args:
            result: マッチを含む :class:`SearchResult`。
        """
        self._file_list_panel.add_result(result)

    def _on_search_completed(
        self,
        results: list[SearchResult],
        elapsed: float,
    ) -> None:
        """検索完了通知を受け取りステータスバー・警告ラベルを更新する。

        Args:
            results: 全検索結果リスト。
            elapsed: 検索所要時間（秒）。
        """
        self._stop_search()
        self._search_panel.set_searching(False)
        self._status_bar.show_progress(False)
        self._status_bar.set_time(elapsed)

        total_matches = sum(r.match_count for r in results)
        truncated_count = sum(1 for r in results if r.truncated)

        if truncated_count:
            self._file_list_panel.set_status(
                f"※ {truncated_count} ファイルで 50 件打ち切りあり",
                is_warning=True,
            )

        self._status_bar.set_message(
            f"検索完了: {len(results)} ファイル / {total_matches} 件"
        )
        self._logger.info(
            "search_completed",
            f"Completed: {len(results)} files, {total_matches} matches",
            elapsed_ms=int(elapsed * 1000),
        )

    def _on_search_error(self, error: str) -> None:
        """検索エラー通知を受け取り、エラーダイアログを表示する。

        Args:
            error: エラーメッセージ文字列。
        """
        self._stop_search()
        self._search_panel.set_searching(False)
        self._status_bar.show_progress(False)
        self._status_bar.set_message(f"エラー: {error}")
        QMessageBox.critical(
            self, "検索エラー", f"検索中にエラーが発生しました:\n{error}"
        )
        self._logger.critical("search_error", f"Search error: {error}")

    # ------------------------------------------------------------------
    # ファイル選択・プレビュー
    # ------------------------------------------------------------------

    def _on_file_selected(self, file_path: str, match_index: int) -> None:
        """ファイルリストで行が選択されたときにプレビューを更新する。

        Args:
            file_path: 選択されたファイルのパス文字列。
            match_index: 最初に移動するマッチのインデックス。
        """
        result = self._file_list_panel.get_result_by_path(file_path)
        if result is None or result.extracted_content is None:
            return

        self._current_result = result
        self._refresh_preview(result, match_index)

    def _refresh_preview(
        self,
        result: SearchResult,
        match_index: int = 0,
        page_filter: int | None = None,
        sheet_filter: str | None = None,
        slide_filter: int | None = None,
    ) -> None:
        """SearchResult を元にプレビュー HTML を生成して表示する。

        Args:
            result: 表示する検索結果。
            match_index: 初期選択するマッチのインデックス。
            page_filter: 表示ページ番号（PDF 用）。``None`` で全ページ表示。
            sheet_filter: 表示シート名（Excel 用）。``None`` で全シート表示。
            slide_filter: 表示スライド番号（PowerPoint 用）。``None`` で全スライド表示。
        """
        content = result.extracted_content
        matches = result.matches

        rendered_html = self._preview_renderer.render_full(
            content,
            matches,
            page_filter=page_filter,
            sheet_filter=sheet_filter,
            slide_filter=slide_filter,
        )

        match_dicts = [
            {
                "location": m.get_location_info(),
                "text": m.text,
                "start": m.start,
                "end": m.end,
            }
            for m in matches
        ]

        file_info_text = _build_file_info_text(
            result, self._metadata_reader, content
        )

        self._preview_panel.set_content(rendered_html, match_dicts, file_info_text)
        _setup_navigation(self._preview_panel, content)

        if match_index < len(matches):
            self._preview_panel.select_match(match_index)

    def _on_navigation_changed(self, value: str) -> None:
        """ページ / シート / スライド切り替え時にプレビューを再レンダリングする。

        Args:
            value: コンボボックスで選択された項目のテキスト
                   （例: ``"ページ 2"`` / ``"Sheet1"`` / ``"スライド 3"``）。
        """
        if self._current_result is None:
            return
        content = self._current_result.extracted_content
        if content is None:
            return

        ext = content.file_path.suffix.lower().lstrip(".")

        if ext == "pdf":
            try:
                page = int(value.replace("ページ ", ""))
            except ValueError:
                page = None
            self._refresh_preview(self._current_result, page_filter=page)

        elif ext == "xlsx":
            self._refresh_preview(self._current_result, sheet_filter=value)

        elif ext == "pptx":
            try:
                slide = int(value.replace("スライド ", ""))
            except ValueError:
                slide = None
            self._refresh_preview(self._current_result, slide_filter=slide)

    # ------------------------------------------------------------------
    # QMainWindow イベント
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        """ウィンドウを閉じる前に検索スレッドを停止する。

        Args:
            event: Qt のクローズイベント。
        """
        self._stop_search()
        self._logger.info("app_closed", "Application closed")
        event.accept()


# ---------------------------------------------------------------------------
# ヘルパー関数（UI 依存なし、純粋ロジック）
# ---------------------------------------------------------------------------

def _build_file_info_text(
    result: SearchResult,
    metadata_reader: MetadataReader,
    content: ExtractedContent | None,
) -> str:
    """プレビューパネルの下部ラベル用ファイル情報テキストを生成する。

    メタデータが実際に存在する場合のみ作成者・作成日を含める。
    ``display_author`` / ``display_created`` は ``"不明"`` を返すことがあるため、
    元フィールドで有無を確認する。

    Args:
        result: 表示対象の SearchResult。
        metadata_reader: メタデータ読み取りオブジェクト。
        content: 抽出されたコンテンツ（文字コード表示用）。

    Returns:
        ``"作成者: ... | 作成日: ..."`` 形式のテキスト。情報がない場合は空文字列。
    """
    parts: list[str] = []

    try:
        metadata: FileMetadata = metadata_reader.read(result.file_info.path)
        # display_{author,created} は "不明" (truthy) を返すため元フィールドで確認する
        if metadata.author or metadata.last_modified_by:
            parts.append(f"作成者: {metadata.display_author}")
        if metadata.created or metadata.modified:
            parts.append(f"作成日: {metadata.display_created}")
    except Exception:
        pass

    if content and content.encoding:
        parts.append(f"文字コード: {content.encoding}")

    return "  |  ".join(parts)


def _setup_navigation(
    preview_panel: PreviewPanel,
    content: ExtractedContent,
) -> None:
    """コンテンツの種別に応じてプレビューパネルのナビゲーションコンボを設定する。

    複数ページ / 複数シート / 複数スライドの場合にのみナビバーを表示する。
    該当しない場合はナビバーを非表示にする。

    Args:
        preview_panel: ナビゲーションを設定する :class:`PreviewPanel`。
        content: ナビゲーションの基準となる :class:`ExtractedContent`。
    """
    ext = content.file_path.suffix.lower().lstrip(".")

    if ext == "pdf" and content.total_pages and content.total_pages > 1:
        items = [f"ページ {p}" for p in range(1, content.total_pages + 1)]
        preview_panel.set_navigation("ページ:", items, items[0] if items else "")

    elif ext == "xlsx" and content.total_sheets and content.total_sheets > 1:
        sheets: list[str] = []
        seen: set[str] = set()
        for block in content.blocks:
            if block.sheet and block.sheet not in seen:
                seen.add(block.sheet)
                sheets.append(block.sheet)
        if len(sheets) > 1:
            preview_panel.set_navigation(
                "シート:", sheets, sheets[0] if sheets else ""
            )

    elif ext == "pptx" and content.total_slides and content.total_slides > 1:
        items = [f"スライド {s}" for s in range(1, content.total_slides + 1)]
        preview_panel.set_navigation("スライド:", items, items[0] if items else "")

    else:
        preview_panel.set_navigation("", [], "")
