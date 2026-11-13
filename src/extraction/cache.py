"""抽出結果キャッシュ

Office/PDFからのテキスト抽出は検索時間の大半を占める。抽出結果を
「パス + 更新時刻 + サイズ」をキーにSQLiteへ保存しておき、ファイルが変わって
いなければ再利用する。検索語を変えて同じフォルダを検索し直すときに効く。
"""

import json
import sqlite3
import threading
import time
import zlib
from pathlib import Path
from typing import Optional

from src.extraction.base import ExtractedContent

# 抽出ロジックを変更したら上げる（古いキャッシュを無効化する）
EXTRACTOR_VERSION = 3


class ExtractionCache:
    """SQLiteによる抽出結果キャッシュ（スレッドセーフ）"""
    
    def __init__(self, db_path: Path, max_size_bytes: int = 500 * 1024 * 1024):
        self._db_path = Path(db_path)
        self._max_size_bytes = max_size_bytes
        self._lock = threading.Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS extraction (
                path TEXT PRIMARY KEY,
                mtime_ns INTEGER NOT NULL,
                size INTEGER NOT NULL,
                version INTEGER NOT NULL,
                last_used REAL NOT NULL,
                data BLOB NOT NULL
            )
            """
        )
        self._conn.commit()
        self._pending = 0
    
    def get(self, path: Path, mtime_ns: int, size: int) -> Optional[ExtractedContent]:
        """キャッシュを取得（ファイルが更新されていれば None）"""
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM extraction WHERE path=? AND mtime_ns=? AND size=? AND version=?",
                (str(path), mtime_ns, size, EXTRACTOR_VERSION),
            ).fetchone()
        if row is None:
            return None
        try:
            return ExtractedContent.from_dict(json.loads(zlib.decompress(row[0])))
        except Exception:
            return None
    
    def put(self, path: Path, mtime_ns: int, size: int, content: ExtractedContent) -> None:
        """キャッシュへ保存（エラーになった抽出結果は保存しない）"""
        if content.error:
            return
        data = zlib.compress(
            json.dumps(content.to_dict(), ensure_ascii=False, default=str).encode("utf-8"), 1
        )
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO extraction VALUES (?,?,?,?,?,?)",
                (str(path), mtime_ns, size, EXTRACTOR_VERSION, time.time(), data),
            )
            self._pending += 1
            if self._pending >= 50:
                self._conn.commit()
                self._pending = 0
    
    def flush(self) -> None:
        with self._lock:
            self._conn.commit()
            self._pending = 0
    
    def prune(self) -> None:
        """容量上限を超えていたら、古いものから削除する"""
        with self._lock:
            self._conn.execute("DELETE FROM extraction WHERE version<>?", (EXTRACTOR_VERSION,))
            total = self._conn.execute(
                "SELECT COALESCE(SUM(LENGTH(data)), 0) FROM extraction"
            ).fetchone()[0]
            if total > self._max_size_bytes:
                rows = self._conn.execute(
                    "SELECT path, LENGTH(data) FROM extraction ORDER BY last_used"
                ).fetchall()
                for path, length in rows:
                    if total <= self._max_size_bytes * 0.8:
                        break
                    self._conn.execute("DELETE FROM extraction WHERE path=?", (path,))
                    total -= length
            self._conn.commit()
    
    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM extraction")
            self._conn.commit()
    
    def close(self) -> None:
        with self._lock:
            self._conn.commit()
            self._conn.close()


_cache: Optional[ExtractionCache] = None
_cache_lock = threading.Lock()


def get_extraction_cache() -> Optional[ExtractionCache]:
    """設定に応じたキャッシュのシングルトン（無効・作成失敗時は None）"""
    global _cache
    from src.common.config import get_config
    
    config = get_config()
    if not config.extraction_cache_enabled:
        return None
    
    with _cache_lock:
        if _cache is None:
            try:
                _cache = ExtractionCache(
                    config.cache_path / "extraction.sqlite",
                    config.cache_max_size_mb * 1024 * 1024,
                )
                _cache.prune()
            except (sqlite3.Error, OSError):
                return None
        return _cache
