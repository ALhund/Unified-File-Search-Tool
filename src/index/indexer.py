"""バックグラウンドの索引更新

登録したフォルダを定期的に調べ、新しいファイル・更新されたファイルを抽出して
検索インデックスに入れる。削除されたファイルは索引から除く。
検索の邪魔をしないよう、同時に処理する数は論理プロセッサの半分までにし、
検索が始まったら中断する。
"""

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot

from src.common.logger import get_logger
from src.enumeration import FileEnumerator, FileInfo
from src.extraction import get_supported_extensions
from src.extraction.cache import get_extraction_cache
from src.search.searcher import run_files, worker_count


@dataclass
class IndexStatus:
    running: bool = False
    folder: str = ""
    done: int = 0
    total: int = 0
    indexed_files: int = 0
    last_finished: Optional[float] = None
    errors: int = 0
    folders: list[str] = field(default_factory=list)


class IndexWorker(QObject):
    """索引の更新（専用スレッドで動かす）"""
    
    progress = Signal(object)  # IndexStatus
    finished = Signal(object)  # IndexStatus
    
    def __init__(self):
        super().__init__()
        self._logger = get_logger("index")
        self._cancelled = False
        self._enumerator: Optional[FileEnumerator] = None
        self.status = IndexStatus()
    
    def cancel(self) -> None:
        """中断する（検索を始めるときなど）"""
        self._cancelled = True
        if self._enumerator is not None:
            self._enumerator.cancel()
    
    @Slot(list, bool)
    def run(self, folders: list[str], include_subfolders: bool = True) -> None:
        self._cancelled = False
        cache = get_extraction_cache()
        status = IndexStatus(running=True, folders=list(folders))
        self.status = status
        if cache is None:
            status.running = False
            self.finished.emit(status)
            return
        
        started = time.time()
        added = removed = 0
        for folder in folders:
            if self._cancelled:
                break
            root = Path(folder)
            if not root.is_dir():
                continue
            status.folder = folder
            self._enumerator = FileEnumerator()
            files = self._enumerator.enumerate(
                root, include_subfolders=include_subfolders, target_extensions=get_supported_extensions()
            ).files
            
            # 削除・移動されたファイルを索引から除く
            existing = {str(f.path) for f in files}
            missing = [p for p in cache.indexed_paths_under(root) if p not in existing]
            if missing:
                removed += cache.remove(missing)
            
            fresh = cache.fresh_paths(files)
            stale = [f for f in files if str(f.path) not in fresh]
            status.done = 0
            status.total = len(stale)
            self.progress.emit(status)
            if not stale:
                continue
            
            stale.sort(key=lambda f: f.size)  # 小さいファイルから（早く多くを検索可能にする）
            last_emit = [0.0]
            
            def on_result(file_info: FileInfo, raw: dict) -> None:
                nonlocal added
                if raw.get("content") is not None:
                    cache.put(file_info.path, file_info.mtime_ns, file_info.size, raw["content"])
                    added += 1
                elif raw.get("error"):
                    status.errors += 1
                status.done += 1
                if time.time() - last_emit[0] > 0.3:
                    last_emit[0] = time.time()
                    self.progress.emit(status)
            
            run_files(
                stale, None, 0, on_result, lambda: self._cancelled, set(),
                max_in_flight=max(1, worker_count() // 2),
            )
            cache.flush()
        
        status.running = False
        status.indexed_files = cache.stats()[0]
        if not self._cancelled:
            status.last_finished = time.time()
        self._logger.info(
            "update", "Index updated", folders=len(folders), added=added, removed=removed,
            cancelled=self._cancelled, elapsed_ms=int((time.time() - started) * 1000),
        )
        self.finished.emit(status)
