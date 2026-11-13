"""原本表示（ページ画像 + マッチ箇所の重ね合わせ）

QGraphicsView でページを縦に並べる。ページ画像はタイルに分け、
画面に見えている部分だけを別スレッドで描画する（数百ページでもすぐ開ける）。
マッチ箇所は「乗算」で重ねるので、下の文字が透けて見える。
"""

import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import shiboken6
from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import QFrame, QGraphicsItem, QGraphicsScene, QGraphicsView, QStyleOptionGraphicsItem

from src.preview.page_document import CSS_PX_PER_PT, PageDocument, PageHit
from src.ui.theme import palette, ui_font

PAGE_GAP = 22.0  # ページの間隔（px, 100% 表示）
LABEL_HEIGHT = 26.0  # ページ見出しの高さ
MARGIN = 20.0
DENSITIES = (1.0, 1.5, 2.0, 3.0)
CACHE_BYTES = 320 * 1024 * 1024

HIT_FILL = QColor(255, 227, 77, 150)
HIT_EDGE = QColor(232, 180, 0, 230)
CURRENT_FILL = QColor(255, 159, 28, 165)
CURRENT_EDGE = QColor(232, 89, 12)


class _TileLoader(QObject):
    """タイルの描画（別スレッド）"""
    
    loaded = Signal(int, int, int, float, object)  # 世代, ページ, タイル, 密度, QImage
    
    def __init__(self):
        super().__init__()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="page-tile")
        self._pending: set[tuple] = set()
        self._lock = threading.Lock()
    
    def request(self, generation: int, document: PageDocument, page: int, tile: int, density: float) -> None:
        key = (generation, page, tile, density)
        with self._lock:
            if key in self._pending:
                return
            self._pending.add(key)
        try:
            self._executor.submit(self._render, key, document)
        except RuntimeError:
            pass
    
    def forget(self) -> None:
        with self._lock:
            self._pending.clear()
    
    def _render(self, key: tuple, document: PageDocument) -> None:
        generation, page, tile, density = key
        image = None
        try:
            data = document.render_tile_rgb(page, tile, density)
            if data is not None:
                width, height, pixels = data
                image = QImage(pixels, width, height, width * 3, QImage.Format.Format_RGB888).copy()
        except Exception:
            image = None
        with self._lock:
            self._pending.discard(key)
        if image is not None:
            self.loaded.emit(generation, page, tile, density, image)
    
    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


class _PageItem(QGraphicsItem):
    """1ページ（見出し・影・ページ画像・マッチ箇所）"""
    
    def __init__(self, view: "PageView", index: int, label: str, width: float, height: float,
                 hits: list[tuple[int, list[QRectF]]]):
        super().__init__()
        self._view = view
        self.index = index
        self.label = label
        self.page_rect = QRectF(0, 0, width, height)
        self.hits = hits  # (マッチ番号, 矩形の一覧)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption)
    
    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(-8, -LABEL_HEIGHT, self.page_rect.width() + 16, self.page_rect.height() + LABEL_HEIGHT + 12)
    
    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget=None) -> None:
        p = palette()
        exposed = option.exposedRect
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        # 見出し（例: シート: 売上  2件）
        painter.setFont(self._view.label_font)
        painter.setPen(QColor(p.text_secondary))
        metrics = QFontMetricsF(self._view.label_font)
        baseline = -LABEL_HEIGHT + 17
        painter.drawText(QPointF(0, baseline), self.label)
        if self.hits:
            text = f"{len(self.hits)}件"
            x = metrics.horizontalAdvance(self.label) + 8
            badge = QRectF(x, baseline - 13, metrics.horizontalAdvance(text) + 14, 18)
            path = QPainterPath()
            path.addRoundedRect(badge, 9, 9)
            painter.fillPath(path, QColor("#FFE34D"))
            painter.setPen(QColor("#3A2A00"))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
        
        # 影と用紙
        page = self.page_rect
        for spread, alpha in ((6, 10), (3, 22), (1, 40)):
            painter.fillRect(page.adjusted(-spread, -spread + 2, spread, spread + 2), QColor(0, 0, 0, alpha))
        painter.fillRect(page, QColor("#FFFFFF"))
        
        # ページ画像（見えているタイルだけ）
        for tile, rect in self._view.tile_rects(self.index):
            if not rect.intersects(exposed):
                continue
            image = self._view.tile_image(self.index, tile)
            if image is not None:
                painter.drawImage(rect, image)
            else:
                painter.fillRect(rect, QColor("#F4F5F7"))
        
        # マッチ箇所
        current = self._view.current_hit
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
        for index, rects in self.hits:
            painter.setBrush(CURRENT_FILL if index == current else HIT_FILL)
            for rect in rects:
                painter.drawRoundedRect(rect, 2, 2)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for index, rects in self.hits:
            is_current = index == current
            painter.setPen(QPen(CURRENT_EDGE if is_current else HIT_EDGE, 2.2 if is_current else 1.1))
            for rect in rects:
                painter.drawRoundedRect(rect, 2, 2)
                if is_current and self._view.pulse > 0:
                    # 現在の箇所を知らせる波紋
                    grow = 16 * (1 - self._view.pulse)
                    ring = QColor(CURRENT_EDGE)
                    ring.setAlphaF(0.85 * self._view.pulse)
                    painter.setPen(QPen(ring, 2))
                    painter.drawRoundedRect(rect.adjusted(-grow, -grow, grow, grow), 4, 4)
                    painter.setPen(QPen(CURRENT_EDGE, 2.2))


class PageView(QGraphicsView):
    """ページを縦に並べて表示するビュー"""
    
    hit_clicked = Signal(int)
    section_changed = Signal(int)
    zoom_step_requested = Signal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        
        self.label_font = ui_font(9, QFont.Weight.DemiBold)
        self.current_hit = -1
        self.pulse = 0.0
        self._document: Optional[PageDocument] = None
        self._generation = 0
        self._items: list[_PageItem] = []
        self._hit_rects: dict[int, tuple[int, QRectF]] = {}  # マッチ番号 → (ページ, 最初の矩形)
        self._zoom = 1.0
        self._cache: OrderedDict[tuple[int, int, float], QImage] = OrderedDict()
        self._cache_bytes = 0
        self._last_section = -1
        
        self._loader = _TileLoader()
        self._loader.loaded.connect(self._on_tile_loaded)
        self._pulse_anim = QVariantAnimation(self, startValue=1.0, endValue=0.0, duration=900, loopCount=2)
        self._pulse_anim.valueChanged.connect(self._on_pulse)
        self.verticalScrollBar().valueChanged.connect(self._update_section)
        self.apply_theme()
    
    # ------------------------------------------------------------------
    
    def apply_theme(self) -> None:
        self.setBackgroundBrush(QColor(palette().preview_bg))
        self.viewport().update()
    
    def shutdown(self) -> None:
        self._loader.shutdown()
    
    def clear(self) -> None:
        self._generation += 1
        self._loader.forget()
        self.scene().clear()
        self._items = []
        self._hit_rects = {}
        self._cache.clear()
        self._cache_bytes = 0
        self._document = None
        self.current_hit = -1
    
    def set_document(self, document: PageDocument, hits: list[PageHit]) -> None:
        self.clear()
        self._document = document
        scale = CSS_PX_PER_PT
        
        by_page: dict[int, list[tuple[int, list[QRectF]]]] = {}
        for index, hit in enumerate(hits):
            rects = [
                QRectF(x0 * scale - 1, y0 * scale - 0.5, (x1 - x0) * scale + 2, (y1 - y0) * scale + 1)
                for x0, y0, x1, y1 in hit.rects
            ]
            by_page.setdefault(hit.page, []).append((index, rects))
        
        y = MARGIN + LABEL_HEIGHT
        max_width = 0.0
        for page_index, layout in enumerate(document.layouts):
            width, height = layout.width * scale, layout.height * scale
            item = _PageItem(self, page_index, document.labels[page_index], width, height, by_page.get(page_index, []))
            item.setPos(-width / 2, y)
            self.scene().addItem(item)
            self._items.append(item)
            for index, rects in by_page.get(page_index, []):
                if rects:
                    self._hit_rects[index] = (page_index, rects[0])
            y += height + PAGE_GAP + LABEL_HEIGHT
            max_width = max(max_width, width)
        
        self.scene().setSceneRect(QRectF(-max_width / 2 - MARGIN, 0, max_width + MARGIN * 2, y + MARGIN))
        self._last_section = -1
        self.verticalScrollBar().setValue(0)
        self._update_section()
    
    # ------------------------------------------------------------------
    # タイル
    # ------------------------------------------------------------------
    
    def tile_rects(self, page_index: int):
        layout = self._document.layouts[page_index]
        for tile in range(layout.tile_count):
            left, top, right, bottom = layout.tile_rect(tile)
            yield tile, QRectF(left * CSS_PX_PER_PT, top * CSS_PX_PER_PT,
                               (right - left) * CSS_PX_PER_PT, (bottom - top) * CSS_PX_PER_PT)
    
    def _wanted_density(self) -> float:
        need = self._zoom * self.devicePixelRatioF()
        for density in DENSITIES:
            if density >= need - 0.05:
                return density
        return DENSITIES[-1]
    
    def tile_image(self, page_index: int, tile: int) -> Optional[QImage]:
        """表示に使うタイル画像（無ければ描画を依頼し、あれば別の密度のもので代用）"""
        wanted = self._wanted_density()
        key = (page_index, tile, wanted)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        if self._document is not None:
            self._loader.request(self._generation, self._document, page_index, tile, wanted)
        for density in sorted(DENSITIES, reverse=True):
            image = self._cache.get((page_index, tile, density))
            if image is not None:
                return image
        return None
    
    def _on_tile_loaded(self, generation: int, page: int, tile: int, density: float, image: QImage) -> None:
        if generation != self._generation or not shiboken6.isValid(self) or page >= len(self._items):
            return
        key = (page, tile, density)
        self._cache[key] = image
        self._cache_bytes += image.sizeInBytes()
        while self._cache_bytes > CACHE_BYTES and len(self._cache) > 1:
            _, old = self._cache.popitem(last=False)
            self._cache_bytes -= old.sizeInBytes()
        item = self._items[page]
        for index, rect in self.tile_rects(page):
            if index == tile:
                item.update(rect)
                break
    
    # ------------------------------------------------------------------
    # ズーム・移動
    # ------------------------------------------------------------------
    
    def set_zoom(self, zoom: float) -> None:
        self._zoom = zoom
        self.setTransform(QTransform.fromScale(zoom, zoom))
    
    def content_width(self) -> float:
        """一番幅の広いページの幅（100% 表示の px）"""
        if not self._items:
            return 0.0
        return max(item.page_rect.width() for item in self._items)
    
    def goto_hit(self, index: int) -> None:
        self.current_hit = index
        target = self._hit_rects.get(index)
        if target is not None:
            page, rect = target
            center = self._items[page].mapToScene(rect.center())
            self.centerOn(center)
            self._pulse_anim.stop()
            self._pulse_anim.start()
        self.viewport().update()
    
    def goto_section(self, index: int) -> None:
        if 0 <= index < len(self._items):
            item = self._items[index]
            top = item.mapToScene(QPointF(0, -LABEL_HEIGHT - 6))
            self.verticalScrollBar().setValue(int(self.mapFromScene(top).y() + self.verticalScrollBar().value()))
    
    def _on_pulse(self, value) -> None:
        self.pulse = float(value)
        target = self._hit_rects.get(self.current_hit)
        if target is not None:
            page, rect = target
            self._items[page].update(rect.adjusted(-24, -24, 24, 24))
    
    def _update_section(self, *_args) -> None:
        if not self._items:
            return
        line = self.mapToScene(0, int(self.viewport().height() * 0.35)).y()
        current = 0
        for item in self._items:
            if item.scenePos().y() - LABEL_HEIGHT <= line:
                current = item.index
            else:
                break
        if current != self._last_section:
            self._last_section = current
            self.section_changed.emit(current)
    
    # ------------------------------------------------------------------
    # マウス
    # ------------------------------------------------------------------
    
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            scene_pos = self.mapToScene(event.position().toPoint())
            for item in self._items:
                local = item.mapFromScene(scene_pos)
                if not item.page_rect.contains(local):
                    continue
                for index, rects in item.hits:
                    if any(r.adjusted(-2, -2, 2, 2).contains(local) for r in rects):
                        self.hit_clicked.emit(index)
                        return
        super().mousePressEvent(event)
    
    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.zoom_step_requested.emit(1 if delta > 0 else -1)
            event.accept()
            return
        super().wheelEvent(event)
