"""プレビュー用のURLスキーム（ufst://）

プレビューのHTMLとページ画像を、ファイルに書き出さずにWebビューへ渡す。
ページ画像は表示領域に入ったものだけが要求されるので（遅延読み込み）、
数百ページの文書でもすぐに開ける。画像の生成は別スレッドで行う。
"""

import itertools
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import shiboken6
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, Signal
from PySide6.QtWebEngineCore import (
    QWebEngineUrlRequestJob,
    QWebEngineUrlScheme,
    QWebEngineUrlSchemeHandler,
)

from src.preview.page_document import PageDocument

SCHEME = b"ufst"
HOST = "preview"
MAX_CACHED_TILES = 48


def register_scheme() -> None:
    """スキームを登録する（QApplication の生成前に呼ぶこと）"""
    scheme = QWebEngineUrlScheme(SCHEME)
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    scheme.setFlags(
        QWebEngineUrlScheme.Flag.SecureScheme
        | QWebEngineUrlScheme.Flag.LocalScheme
        | QWebEngineUrlScheme.Flag.LocalAccessAllowed
    )
    QWebEngineUrlScheme.registerScheme(scheme)


class PreviewStore:
    """表示中のプレビュー（HTMLとページ文書）を保持する"""
    
    def __init__(self):
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._html: dict[str, bytes] = {}
        self._documents: dict[str, PageDocument] = {}
        self._tiles: OrderedDict[tuple[str, int, int], bytes] = OrderedDict()
        self.dark = False  # ダークテーマで配信する
    
    def new_id(self) -> str:
        return f"d{next(self._ids)}"
    
    def put(self, doc_id: str, html: str, document: Optional[PageDocument]) -> None:
        with self._lock:
            self._html[doc_id] = html.encode("utf-8")
            if document is not None:
                self._documents[doc_id] = document
    
    def release_except(self, keep_id: Optional[str]) -> None:
        """表示しなくなったプレビューを破棄する"""
        with self._lock:
            stale = [d for d in self._html if d != keep_id]
            documents = [self._documents.pop(d) for d in stale if d in self._documents]
            for doc_id in stale:
                self._html.pop(doc_id, None)
            for key in [k for k in self._tiles if k[0] != keep_id]:
                del self._tiles[key]
        for document in documents:
            document.close()
    
    def html(self, doc_id: str) -> Optional[bytes]:
        with self._lock:
            data = self._html.get(doc_id)
        if data is not None and self.dark:
            data = data.replace(b"<html lang='ja'>", b"<html lang='ja' class='dark'>", 1)
        return data
    
    def tile(self, doc_id: str, page: int, tile: int) -> Optional[bytes]:
        key = (doc_id, page, tile)
        with self._lock:
            if key in self._tiles:
                self._tiles.move_to_end(key)
                return self._tiles[key]
            document = self._documents.get(doc_id)
        if document is None:
            return None
        
        data = document.render_tile(page, tile)
        if data is not None:
            with self._lock:
                self._tiles[key] = data
                while len(self._tiles) > MAX_CACHED_TILES:
                    self._tiles.popitem(last=False)
        return data
    
    def url(self, doc_id: str) -> str:
        return f"{SCHEME.decode()}://{HOST}/{doc_id}/index.html"
    
    @staticmethod
    def tile_prefix() -> str:
        """HTMLからの相対パスでのタイル画像の接頭辞"""
        return "tile"


class PreviewSchemeHandler(QWebEngineUrlSchemeHandler):
    """ufst:// へのリクエストに応答する"""
    
    _tile_ready = Signal(object, object)
    
    def __init__(self, store: PreviewStore, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._store = store
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="preview-tile")
        self._tile_ready.connect(self._reply_tile)
    
    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
    
    def requestStarted(self, job: QWebEngineUrlRequestJob) -> None:
        parts = [p for p in job.requestUrl().path().split("/") if p]
        
        # /<doc>/index.html
        if len(parts) == 2 and parts[1] == "index.html":
            data = self._store.html(parts[0])
            if data is None:
                job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            else:
                self._reply(job, b"text/html", data)
            return
        
        # /<doc>/tile/<page>/<tile>.png
        if len(parts) == 4 and parts[1] == "tile":
            try:
                page, tile = int(parts[2]), int(parts[3].split(".")[0])
            except ValueError:
                job.fail(QWebEngineUrlRequestJob.Error.UrlInvalid)
                return
            doc_id = parts[0]
            try:
                self._executor.submit(self._render, job, doc_id, page, tile)
            except RuntimeError:
                job.fail(QWebEngineUrlRequestJob.Error.RequestAborted)
            return
        
        job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
    
    def _render(self, job, doc_id: str, page: int, tile: int) -> None:
        """（描画スレッド）タイルを生成してUIスレッドへ返す"""
        try:
            data = self._store.tile(doc_id, page, tile)
        except Exception:
            data = None
        self._tile_ready.emit(job, data)
    
    def _reply_tile(self, job, data) -> None:
        if not shiboken6.isValid(job):
            return  # 応答前にページが切り替わった
        if data is None:
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
        else:
            self._reply(job, b"image/png", data)
    
    @staticmethod
    def _reply(job: QWebEngineUrlRequestJob, content_type: bytes, data: bytes) -> None:
        buffer = QBuffer(job)
        buffer.setData(QByteArray(data))
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        job.reply(content_type, buffer)
