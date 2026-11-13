"""二重起動の防止

すでに起動している（タスクトレイに常駐している）ときに、もう一度起動したら
新しく起動せず、動いている方のウィンドウを前面に出す。
"""

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QFileSystemWatcher, QLockFile, QObject


class SingleInstance(QObject):
    def __init__(self, folder: Path, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._folder = Path(folder)
        self._folder.mkdir(parents=True, exist_ok=True)
        self._lock = QLockFile(str(self._folder / "app.lock"))
        self._lock.setStaleLockTime(0)  # 異常終了で残ったロックはプロセスの有無で判定する
        self._request = self._folder / "show.request"
        self._watcher: Optional[QFileSystemWatcher] = None
    
    def acquire(self) -> bool:
        """自分が最初の起動なら True"""
        return self._lock.tryLock(100)
    
    def notify_running(self) -> None:
        """起動中のアプリにウィンドウ表示を頼む"""
        try:
            self._request.write_text("show", encoding="utf-8")
        except OSError:
            pass
    
    def listen(self, on_request: Callable[[], None]) -> None:
        """ほかの起動からの表示依頼を受け付ける"""
        self._request.unlink(missing_ok=True)
        self._watcher = QFileSystemWatcher([str(self._folder)], self)
        
        def changed(_path: str) -> None:
            if self._request.exists():
                self._request.unlink(missing_ok=True)
                on_request()
        
        self._watcher.directoryChanged.connect(changed)
    
    def release(self) -> None:
        self._lock.unlock()
