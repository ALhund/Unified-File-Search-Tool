"""抽出・レンダーキャッシュモジュール。

LRU ベースのキャッシュで、同一ファイルの再抽出・再レンダリングを回避する。
キーにファイルパスと更新日時を含むため、ファイル変更時は自動で無効化される。
"""

import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from src.extraction.base import ExtractedContent


# ---------------------------------------------------------------------------
# キャッシュキー
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _CacheKey:
    """ファイルパスと更新日時を組み合わせたキャッシュキー。"""

    file_path: str
    mtime_ns: int


# ---------------------------------------------------------------------------
# 抽出キャッシュ
# ---------------------------------------------------------------------------

class ExtractionCache:
    """スレッドセーフな LRU キャッシュ (:class:`ExtractedContent` 用)。

    キーは ``(file_path, mtime_ns)`` の組み合わせで、
    ファイルが更新されるとキャッシュミスになる。
    """

    def __init__(self, max_entries: int = 100) -> None:
        self._max_entries = max_entries
        self._cache: OrderedDict[_CacheKey, ExtractedContent] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, file_path: Path) -> ExtractedContent | None:
        """キャッシュ済みコンテンツがあれば返す。なければ ``None``。"""
        try:
            mtime_ns = file_path.stat().st_mtime_ns
        except OSError:
            return None

        key = _CacheKey(str(file_path), mtime_ns)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def put(self, file_path: Path, content: ExtractedContent) -> None:
        """抽出結果をキャッシュに格納する。"""
        try:
            mtime_ns = file_path.stat().st_mtime_ns
        except OSError:
            return

        key = _CacheKey(str(file_path), mtime_ns)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = content
            else:
                self._cache[key] = content
                if len(self._cache) > self._max_entries:
                    self._cache.popitem(last=False)

    def clear(self) -> None:
        """全キャッシュエントリをクリアする。"""
        with self._lock:
            self._cache.clear()

    @property
    def size(self) -> int:
        """現在のキャッシュエントリ数。"""
        return len(self._cache)


# ---------------------------------------------------------------------------
# レンダーキャッシュ
# ---------------------------------------------------------------------------

class RenderCache:
    """スレッドセーフな LRU キャッシュ（レンダリング済み HTML 用）。

    キーはファイルパス・更新日時・フィルタパラメータ・マッチハッシュを
    組み合わせた文字列。
    """

    def __init__(self, max_entries: int = 50) -> None:
        self._max_entries = max_entries
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, cache_key: str) -> str | None:
        """キャッシュ済み HTML があれば返す。なければ ``None``。"""
        with self._lock:
            if cache_key in self._cache:
                self._cache.move_to_end(cache_key)
                return self._cache[cache_key]
        return None

    def put(self, cache_key: str, html: str) -> None:
        """レンダリング済み HTML をキャッシュに格納する。"""
        with self._lock:
            if cache_key in self._cache:
                self._cache.move_to_end(cache_key)
                self._cache[cache_key] = html
            else:
                self._cache[cache_key] = html
                if len(self._cache) > self._max_entries:
                    self._cache.popitem(last=False)

    def clear(self) -> None:
        """全キャッシュエントリをクリアする。"""
        with self._lock:
            self._cache.clear()

    @property
    def size(self) -> int:
        """現在のキャッシュエントリ数。"""
        return len(self._cache)


# ---------------------------------------------------------------------------
# シングルトンアクセス
# ---------------------------------------------------------------------------

_extraction_cache: ExtractionCache | None = None
_render_cache: RenderCache | None = None
_singleton_lock = threading.Lock()


def get_extraction_cache() -> ExtractionCache:
    """抽出キャッシュのシングルトンインスタンスを返す。"""
    global _extraction_cache
    if _extraction_cache is None:
        with _singleton_lock:
            if _extraction_cache is None:
                _extraction_cache = ExtractionCache()
    return _extraction_cache


def get_render_cache() -> RenderCache:
    """レンダーキャッシュのシングルトンインスタンスを返す。"""
    global _render_cache
    if _render_cache is None:
        with _singleton_lock:
            if _render_cache is None:
                _render_cache = RenderCache()
    return _render_cache
