"""検索インデックス（抽出結果の保存と全文検索）

Office/PDF からのテキスト抽出は検索時間の大半を占める。抽出結果を
「パス + 更新時刻 + サイズ」をキーに SQLite へ保存し、ファイルが変わっていなければ再利用する。

あわせて SQLite の全文検索（FTS5, trigram）で、検索語を含むファイルを索引から一瞬で絞り込む。
索引には全角/半角・大文字/小文字をそろえた文字列を入れるので、どの検索条件でも
「含む可能性のあるファイル」を漏れなく取り出せる（最終的な一致判定は従来どおり行う）。
"""

import json
import os
import sqlite3
import threading
import time
import zlib
from pathlib import Path
from typing import Iterable, Optional

from src.common.textnorm import fold_text
from src.extraction.base import ExtractedContent

# 抽出ロジックを変更したら上げる（古い抽出結果を無効化する）
EXTRACTOR_VERSION = 4
DB_NAME = "index.sqlite"
# trigram の索引が使える最小の文字数（これ未満は SQLite 内での全文走査で絞り込む）
TRIGRAM_MIN = 3


def index_text(content: ExtractedContent) -> str:
    """索引に入れる文字列（全角/半角・大文字/小文字をそろえる）"""
    return fold_text("\n".join(b.text for b in content.blocks), True, True).text


def encode_content(content: ExtractedContent) -> bytes:
    return zlib.compress(json.dumps(content.to_dict(), ensure_ascii=False, default=str).encode("utf-8"), 1)


def decode_content(data: bytes) -> Optional[ExtractedContent]:
    try:
        return ExtractedContent.from_dict(json.loads(zlib.decompress(data)))
    except Exception:
        return None


def _connect(path: Path, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, check_same_thread=False, timeout=30)
    else:
        conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


class ExtractionCache:
    """抽出結果と全文検索の索引（スレッドセーフ。書き込みはこのオブジェクト経由のみ）"""
    
    def __init__(self, db_path: Path, max_size_bytes: int = 500 * 1024 * 1024):
        self.db_path = Path(db_path)
        self._max_size_bytes = max_size_bytes
        self._lock = threading.RLock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = _connect(self.db_path)
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY,
                path TEXT UNIQUE NOT NULL,
                mtime_ns INTEGER NOT NULL,
                size INTEGER NOT NULL,
                version INTEGER NOT NULL,
                last_used REAL NOT NULL,
                data BLOB NOT NULL
            );
            """
        )
        try:
            self._conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(body, tokenize='trigram')")
            self.fts_available = True
        except sqlite3.OperationalError:
            self.fts_available = False  # 古い SQLite では全文検索なしで動く
        self._conn.commit()
        self._pending = 0
    
    # ------------------------------------------------------------------
    # 読み出し
    # ------------------------------------------------------------------
    
    def get(self, path: Path, mtime_ns: int, size: int) -> Optional[ExtractedContent]:
        """抽出結果を取得（ファイルが更新されていれば None）"""
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM files WHERE path=? AND mtime_ns=? AND size=? AND version=?",
                (str(path), mtime_ns, size, EXTRACTOR_VERSION),
            ).fetchone()
        return decode_content(row[0]) if row else None
    
    def fresh_paths(self, files: Iterable) -> set[str]:
        """索引が最新（更新時刻・サイズが一致）のファイルのパス"""
        wanted = {str(f.path): (f.mtime_ns, f.size) for f in files}
        fresh: set[str] = set()
        paths = list(wanted)
        with self._lock:
            for i in range(0, len(paths), 500):
                chunk = paths[i:i + 500]
                rows = self._conn.execute(
                    f"SELECT path, mtime_ns, size FROM files WHERE version=? AND path IN ({','.join('?' * len(chunk))})",
                    (EXTRACTOR_VERSION, *chunk),
                ).fetchall()
                for path, mtime_ns, size in rows:
                    if wanted.get(path) == (mtime_ns, size):
                        fresh.add(path)
        return fresh
    
    def candidates(self, terms: list[str], require_all: bool) -> Optional[set[str]]:
        """検索語を含む可能性のあるファイルのパス（索引が使えなければ None）
        
        terms は全角/半角・大文字/小文字をそろえた語。
        """
        if not self.fts_available or not terms:
            return None
        parts: list[str] = []
        params: list[str] = []
        for term in terms:
            if not term:
                return None
            if len(term) >= TRIGRAM_MIN:
                parts.append("SELECT rowid FROM fts WHERE fts MATCH ?")
                params.append('"' + term.replace('"', '""') + '"')
            else:
                escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                parts.append("SELECT rowid FROM fts WHERE body LIKE ? ESCAPE '\\'")
                params.append(f"%{escaped}%")
        joined = (" INTERSECT " if require_all else " UNION ").join(parts)
        with self._lock:
            rows = self._conn.execute(f"SELECT path FROM files WHERE id IN ({joined})", params).fetchall()
        return {row[0] for row in rows}
    
    def stats(self) -> tuple[int, int]:
        """(ファイル数, 使用量バイト)"""
        with self._lock:
            count = self._conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        try:
            size = sum(p.stat().st_size for p in self.db_path.parent.glob(self.db_path.name + "*"))
        except OSError:
            size = 0
        return count, size
    
    def indexed_paths_under(self, folder: Path) -> list[str]:
        prefix = str(folder).rstrip("\\/") + os.sep
        with self._lock:
            rows = self._conn.execute(
                "SELECT path FROM files WHERE path >= ? AND path < ?",
                (prefix, prefix + "\U0010ffff"),
            ).fetchall()
        return [r[0] for r in rows]
    
    # ------------------------------------------------------------------
    # 書き込み
    # ------------------------------------------------------------------
    
    def put(self, path: Path, mtime_ns: int, size: int, content: ExtractedContent) -> None:
        """抽出結果を保存して索引に入れる（エラーになった抽出結果は保存しない）"""
        if content.error:
            return
        data = encode_content(content)
        body = index_text(content)
        with self._lock:
            row = self._conn.execute("SELECT id FROM files WHERE path=?", (str(path),)).fetchone()
            if row:
                file_id = row[0]
                self._conn.execute(
                    "UPDATE files SET mtime_ns=?, size=?, version=?, last_used=?, data=? WHERE id=?",
                    (mtime_ns, size, EXTRACTOR_VERSION, time.time(), data, file_id),
                )
                if self.fts_available:
                    self._conn.execute("DELETE FROM fts WHERE rowid=?", (file_id,))
            else:
                cursor = self._conn.execute(
                    "INSERT INTO files (path, mtime_ns, size, version, last_used, data) VALUES (?,?,?,?,?,?)",
                    (str(path), mtime_ns, size, EXTRACTOR_VERSION, time.time(), data),
                )
                file_id = cursor.lastrowid
            if self.fts_available:
                self._conn.execute("INSERT INTO fts (rowid, body) VALUES (?, ?)", (file_id, body))
            self._pending += 1
            if self._pending >= 50:
                self._conn.commit()
                self._pending = 0
    
    def remove(self, paths: Iterable[str]) -> int:
        """削除されたファイルを索引から除く"""
        removed = 0
        with self._lock:
            for path in paths:
                row = self._conn.execute("SELECT id FROM files WHERE path=?", (path,)).fetchone()
                if row is None:
                    continue
                self._conn.execute("DELETE FROM files WHERE id=?", (row[0],))
                if self.fts_available:
                    self._conn.execute("DELETE FROM fts WHERE rowid=?", (row[0],))
                removed += 1
            self._conn.commit()
        return removed
    
    def flush(self) -> None:
        with self._lock:
            self._conn.commit()
            self._pending = 0
    
    def prune(self) -> None:
        """古い版の抽出結果を消し、容量上限を超えていたら古いものから削除する"""
        with self._lock:
            stale = [r[0] for r in self._conn.execute(
                "SELECT path FROM files WHERE version<>?", (EXTRACTOR_VERSION,)
            ).fetchall()]
        if stale:
            self.remove(stale)
        with self._lock:
            total = self._conn.execute("SELECT COALESCE(SUM(LENGTH(data)), 0) FROM files").fetchone()[0]
            if total <= self._max_size_bytes:
                return
            rows = self._conn.execute("SELECT path, LENGTH(data) FROM files ORDER BY last_used").fetchall()
        victims = []
        for path, length in rows:
            if total <= self._max_size_bytes * 0.8:
                break
            victims.append(path)
            total -= length
        self.remove(victims)
    
    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM files")
            if self.fts_available:
                self._conn.execute("DELETE FROM fts")
            self._conn.commit()
            self._conn.execute("VACUUM")
    
    def close(self) -> None:
        with self._lock:
            self._conn.commit()
            self._conn.close()


# ---------------------------------------------------------------------------
# 読み取り専用の接続（検索ワーカープロセスが自分で抽出結果を読む）
# ---------------------------------------------------------------------------

_reader: Optional[sqlite3.Connection] = None
_reader_path: Optional[Path] = None


def read_cached(db_path: str, path: str, mtime_ns: int, size: int) -> Optional[ExtractedContent]:
    global _reader, _reader_path
    try:
        if _reader is None or _reader_path != Path(db_path):
            _reader = _connect(Path(db_path), readonly=True)
            _reader_path = Path(db_path)
        row = _reader.execute(
            "SELECT data FROM files WHERE path=? AND mtime_ns=? AND size=? AND version=?",
            (path, mtime_ns, size, EXTRACTOR_VERSION),
        ).fetchone()
    except sqlite3.Error:
        return None
    return decode_content(row[0]) if row else None


_cache: Optional[ExtractionCache] = None
_cache_lock = threading.Lock()


def get_extraction_cache() -> Optional[ExtractionCache]:
    """設定に応じたインデックスのシングルトン（無効・作成失敗時は None）"""
    global _cache
    from src.common.config import get_config
    
    config = get_config()
    if not config.extraction_cache_enabled:
        return None
    
    with _cache_lock:
        if _cache is None:
            try:
                old = config.cache_path / "extraction.sqlite"
                for leftover in (old, old.with_name(old.name + "-wal"), old.with_name(old.name + "-shm")):
                    leftover.unlink(missing_ok=True)  # 以前の形式のキャッシュは使わない
                _cache = ExtractionCache(
                    config.cache_path / DB_NAME,
                    config.cache_max_size_mb * 1024 * 1024,
                )
                _cache.prune()
            except (sqlite3.Error, OSError):
                return None
        return _cache
