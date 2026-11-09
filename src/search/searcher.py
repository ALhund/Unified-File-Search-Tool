"""検索モジュール

ファイル内容を検索し、マッチ箇所を返す。

- テキスト抽出はキャッシュ（SQLite）を優先し、未キャッシュ分は複数プロセスで並列に抽出する
- 照合は全角/半角・大文字/小文字を吸収して行う
"""

import multiprocessing
import os
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from typing import Callable, Optional

from src.common.config import get_config
from src.common.logger import get_logger
from src.enumeration import FileInfo
from src.extraction import ExtractedContent, extract_file
from src.extraction.cache import get_extraction_cache
from src.search.query import CompiledQuery, SearchOptions

# マッチ前後に付ける文脈の文字数
CONTEXT_CHARS = 40
# これ未満の件数ならプロセス起動のコストに見合わないので直列で処理する
PARALLEL_THRESHOLD = 8


@dataclass
class MatchInfo:
    """マッチ情報"""
    location: str  # 位置情報（例: "シート: 売上, セル B3"）
    matched_text: str  # マッチした部分
    before: str  # 直前の文脈
    after: str  # 直後の文脈
    block_index: int  # ExtractedContent.blocks 内の位置
    start: int  # ブロック内の開始位置
    end: int  # ブロック内の終了位置
    page: Optional[int] = None
    sheet: Optional[str] = None
    slide: Optional[int] = None
    
    @property
    def snippet(self) -> str:
        """一覧表示用の抜粋"""
        return f"{self.before}{self.matched_text}{self.after}".replace("\n", " ")
    
    def get_location_info(self) -> str:
        return self.location


@dataclass
class SearchResult:
    """検索結果（1ファイル分）"""
    file_info: FileInfo
    matches: list[MatchInfo] = field(default_factory=list)
    error: Optional[str] = None
    truncated: bool = False  # 上限件数で打ち切られたか
    
    @property
    def match_count(self) -> int:
        return len(self.matches)
    
    @property
    def display_count(self) -> str:
        """表示用のカウント（上限超は '50>'）"""
        if self.truncated:
            return f"{self.match_count}>"
        return str(self.match_count)


@dataclass
class SearchSummary:
    """検索全体の集計"""
    total_files: int = 0
    matched_files: int = 0
    total_matches: int = 0
    error_files: int = 0
    cache_hits: int = 0
    elapsed: float = 0.0
    cancelled: bool = False


def search_content(
    content: ExtractedContent,
    query: CompiledQuery,
    max_matches: int,
) -> tuple[list[MatchInfo], bool]:
    """抽出済みコンテンツを検索する
    
    Returns:
        (マッチ一覧, 上限で打ち切ったか)。AND検索で全ての語が揃わない場合は空。
    """
    matches: list[MatchInfo] = []
    seen_terms: set[int] = set()
    truncated = False
    
    for block_index, block in enumerate(content.blocks):
        # 上限到達後は、AND検索の残りの語が存在するかだけを確認する
        if truncated and (not query.require_all or len(seen_terms) == query.term_count):
            break
        
        text = block.text
        hits = list(query.finditer(text))
        if not hits or query.is_excluded(text):
            continue
        
        location = None
        for start, end, term_index in hits:
            seen_terms.add(term_index)
            if len(matches) >= max_matches:
                truncated = True
                continue
            if location is None:
                location = block.get_location_info()
            matches.append(MatchInfo(
                location=location,
                matched_text=text[start:end],
                before=_context_before(text, start),
                after=_context_after(text, end),
                block_index=block_index,
                start=start,
                end=end,
                page=block.page,
                sheet=block.sheet,
                slide=block.slide,
            ))
    
    if query.require_all and len(seen_terms) < query.term_count:
        return [], False
    return matches, truncated


def _context_before(text: str, start: int) -> str:
    begin = max(0, start - CONTEXT_CHARS)
    return ("…" if begin > 0 else "") + text[begin:start]


def _context_after(text: str, end: int) -> str:
    stop = min(len(text), end + CONTEXT_CHARS)
    return text[end:stop] + ("…" if stop < len(text) else "")


# ---------------------------------------------------------------------------
# 並列抽出用のプロセスプール（アプリ全体で使い回す）
# ---------------------------------------------------------------------------

_pool: Optional[ProcessPoolExecutor] = None
_pool_lock = threading.Lock()


def _worker_count() -> int:
    configured = get_config().search_workers
    if configured > 0:
        return configured
    return max(1, min(8, (os.cpu_count() or 2) - 1))


def _get_pool() -> Optional[ProcessPoolExecutor]:
    global _pool
    with _pool_lock:
        if _pool is None:
            workers = _worker_count()
            if workers <= 1:
                return None
            _pool = ProcessPoolExecutor(
                max_workers=workers,
                mp_context=multiprocessing.get_context("spawn"),
            )
        return _pool


def shutdown_pool() -> None:
    """プロセスプールを終了する（アプリ終了時に呼ぶ）"""
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.shutdown(wait=False, cancel_futures=True)
            _pool = None


def load_content(file_info: FileInfo) -> ExtractedContent:
    """キャッシュを使ってファイルの内容を取得する（プレビュー用）"""
    cache = get_extraction_cache()
    if cache is not None:
        cached = cache.get(file_info.path, file_info.mtime_ns, file_info.size)
        if cached is not None:
            return cached
    content = extract_file(str(file_info.path))
    if cache is not None:
        cache.put(file_info.path, file_info.mtime_ns, file_info.size, content)
    return content


class Searcher:
    """検索クラス"""
    
    def __init__(self):
        self._logger = get_logger("search")
        self._config = get_config()
        self._cancelled = False
    
    def cancel(self) -> None:
        """検索をキャンセル"""
        self._cancelled = True
    
    def reset(self) -> None:
        """キャンセル状態をリセット"""
        self._cancelled = False
    
    def search_files(
        self,
        files: list[FileInfo],
        options: SearchOptions,
        result_callback: Optional[Callable[[SearchResult], None]] = None,
        progress_callback: Optional[Callable[[int, int, int, int], None]] = None,
    ) -> SearchSummary:
        """複数ファイルを検索
        
        Args:
            files: 検索対象ファイル一覧
            options: 検索オプション（不正な場合は QueryError）
            result_callback: マッチ（またはエラー）のあったファイルごとに呼ばれる
            progress_callback: 進捗(処理済みbytes, 総bytes, 処理済み件数, 総件数)
        
        Returns:
            検索全体の集計
        """
        self._cancelled = False
        query = CompiledQuery(options)
        max_matches = self._config.search_max_matches_per_file
        cache = get_extraction_cache()
        
        summary = SearchSummary(total_files=len(files))
        total_bytes = sum(f.size for f in files)
        processed = {"bytes": 0, "files": 0}
        start_time = time.time()
        
        self._logger.info(
            "start",
            f"Search started: '{options.query}'",
            file_count=len(files),
            total_bytes=total_bytes,
            use_regex=options.use_regex,
        )
        
        def handle(file_info: FileInfo, content: ExtractedContent) -> None:
            result = SearchResult(file_info=file_info)
            if content.error:
                result.error = content.error
                summary.error_files += 1
            else:
                result.matches, result.truncated = search_content(content, query, max_matches)
                if result.matches:
                    summary.matched_files += 1
                    summary.total_matches += result.match_count
            
            if (result.matches or result.error) and result_callback:
                result_callback(result)
            
            processed["bytes"] += file_info.size
            processed["files"] += 1
            if progress_callback:
                progress_callback(processed["bytes"], total_bytes, processed["files"], len(files))
        
        # 1. キャッシュ済みのファイルを先に処理する（すぐ結果が出る）
        pending: list[FileInfo] = []
        for file_info in files:
            if self._cancelled:
                break
            cached = cache.get(file_info.path, file_info.mtime_ns, file_info.size) if cache else None
            if cached is not None:
                summary.cache_hits += 1
                handle(file_info, cached)
            else:
                pending.append(file_info)
        
        # 2. 未キャッシュ分を抽出する（件数が多ければ並列）
        def handle_extracted(file_info: FileInfo, content: ExtractedContent) -> None:
            if cache is not None:
                cache.put(file_info.path, file_info.mtime_ns, file_info.size, content)
            handle(file_info, content)
        
        if pending and not self._cancelled:
            # 大きいファイルから投入して、並列処理の終盤の待ちを短くする
            pending.sort(key=lambda f: -f.size)
            remaining = self._extract_parallel(pending, handle_extracted)
            for file_info in remaining:
                if self._cancelled:
                    break
                handle_extracted(file_info, extract_file(str(file_info.path)))
        
        if cache is not None:
            cache.flush()
        
        summary.cancelled = self._cancelled
        summary.elapsed = time.time() - start_time
        self._logger.info(
            "end",
            f"Search completed: {summary.matched_files} files matched",
            matched_files=summary.matched_files,
            total_matches=summary.total_matches,
            cache_hits=summary.cache_hits,
            cancelled=summary.cancelled,
            elapsed_ms=int(summary.elapsed * 1000),
        )
        return summary
    
    def _extract_parallel(
        self,
        files: list[FileInfo],
        handle: Callable[[FileInfo, ExtractedContent], None],
    ) -> list[FileInfo]:
        """プロセスプールで抽出する。処理できなかったファイルを返す（直列処理に回す）"""
        if len(files) < PARALLEL_THRESHOLD:
            return files
        try:
            pool = _get_pool()
        except Exception as e:
            self._logger.warning("pool", "Failed to start worker processes", exception_message=str(e))
            return files
        if pool is None:
            return files
        
        done: set[int] = set()
        try:
            futures = {pool.submit(extract_file, str(f.path)): i for i, f in enumerate(files)}
            for future in as_completed(futures):
                index = futures[future]
                if self._cancelled:
                    for f in futures:
                        f.cancel()
                    return []
                try:
                    content = future.result()
                except BrokenProcessPool:
                    raise
                except Exception as e:
                    content = ExtractedContent(file_path=files[index].path, error=str(e) or type(e).__name__)
                done.add(index)
                handle(files[index], content)
        except BrokenProcessPool as e:
            # ワーカーが異常終了した場合は残りを直列で処理する
            self._logger.warning("pool", "Worker process pool is broken", exception_message=str(e))
            shutdown_pool()
        
        return [f for i, f in enumerate(files) if i not in done]
