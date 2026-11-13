"""ページ画像によるプレビュー（PDF / PDFへ変換したOfficeファイル）

PDFium（pypdfium2）でページを画像化し、検索語の位置（矩形）を文字単位の座標から求める。
画像の上に矩形を重ねることで、元のレイアウトを崩さずにマッチ箇所を強調できる。
"""

import io
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.common.pdf_layout import PDFIUM_LOCK, merge_rects, open_document, page_blocks, page_lines
from src.search.query import CompiledQuery

# 1pt（1/72インチ）あたりのCSSピクセル数
CSS_PX_PER_PT = 96 / 72
# 画面表示より高精細に描画する倍率（ズームしても文字がぼやけにくい）
RENDER_DENSITY = 1.5
# タイル1枚の最大サイズ（表示上のpt）。巨大なシートは縦横に分割して必要な部分だけ描画する
TILE_WIDTH_PT = 1300.0
TILE_HEIGHT_PT = 1100.0
CONTEXT_CHARS = 30
# Excelの行番号の標準的な文字サイズ（縮小率の推定に使う）
SHEET_HEADING_FONT_PT = 11.0
MAX_ZOOM = 10.0

Rect = tuple[float, float, float, float]


@dataclass
class PageHit:
    """ページ上のマッチ箇所"""
    page: int  # 0始まり
    rects: list[Rect]  # 表示座標（pt）。行をまたぐ場合は複数
    text: str
    before: str = ""
    after: str = ""


@dataclass
class PageLayout:
    """ページの表示寸法とタイル分割
    
    元ページ（左上原点）のうち clip の範囲を zoom 倍して表示する。
    （Excelは用紙に収めるため縮小出力されるので、余白を切り落として元の大きさに戻す）
    """
    clip: Rect  # 表示する範囲（元ページの座標, pt）
    zoom: float = 1.0
    page_width: float = 0.0  # 元ページの大きさ（描画時の切り抜き計算用）
    page_height: float = 0.0
    
    def __post_init__(self):
        if not self.page_width:
            self.page_width = self.clip[2]
        if not self.page_height:
            self.page_height = self.clip[3]
        self.width = (self.clip[2] - self.clip[0]) * self.zoom  # 表示上の幅（pt）
        self.height = (self.clip[3] - self.clip[1]) * self.zoom
        self.cols = _split_count(self.width, TILE_WIDTH_PT)
        self.rows = _split_count(self.height, TILE_HEIGHT_PT)
        self.tile_width = self.width / self.cols
        self.tile_height = self.height / self.rows
    
    @property
    def tile_count(self) -> int:
        return self.cols * self.rows
    
    def tile_rect(self, tile: int) -> Rect:
        """タイルの範囲（表示座標, pt）"""
        row, col = divmod(tile, self.cols)
        left = col * self.tile_width
        top = row * self.tile_height
        return left, top, left + self.tile_width, top + self.tile_height
    
    def to_display(self, rect: Rect) -> Rect:
        """元ページの座標 → 表示座標"""
        x0, y0 = self.clip[0], self.clip[1]
        return (
            (rect[0] - x0) * self.zoom,
            (rect[1] - y0) * self.zoom,
            (rect[2] - x0) * self.zoom,
            (rect[3] - y0) * self.zoom,
        )


def _split_count(length: float, limit: float) -> int:
    # わずかに超えるだけなら分割しない
    return 1 if length <= limit * 1.15 else math.ceil(length / limit)


class PageDocument:
    """ページ画像として表示する文書"""
    
    def __init__(
        self,
        pdf_path: Path,
        labels: Optional[list[str]] = None,
        fit_to_content: bool = False,
    ):
        """
        Args:
            pdf_path: 表示するPDF
            labels: ページごとの見出し（シート名など）。ページ数が一致するときだけ使う
            fit_to_content: 余白を切り落とし、縮小出力を元の大きさに戻す（Excel用）
        """
        self.pdf_path = Path(pdf_path)
        self._closed = False
        with PDFIUM_LOCK:
            self._doc = open_document(self.pdf_path)
            self.layouts: list[PageLayout] = []
            for index in range(len(self._doc)):
                page = self._doc[index]
                try:
                    if page.get_rotation():
                        page.set_rotation(0)
                    left, bottom, right, top = page.get_cropbox()
                    width, height = right - left, top - bottom
                    if fit_to_content:
                        self.layouts.append(_content_layout(page, width, height))
                    else:
                        self.layouts.append(PageLayout((0.0, 0.0, width, height)))
                finally:
                    page.close()
        
        if labels and len(labels) == len(self.layouts):
            self.labels = labels
        else:
            self.labels = [f"ページ {i + 1}" for i in range(len(self.layouts))]
    
    @property
    def page_count(self) -> int:
        return len(self.layouts)
    
    def close(self) -> None:
        with PDFIUM_LOCK:
            if not self._closed:
                self._closed = True
                self._doc.close()
    
    # ------------------------------------------------------------------
    # 描画
    # ------------------------------------------------------------------
    
    def render_tile(self, page_index: int, tile: int) -> Optional[bytes]:
        """ページの一部（タイル）をPNGで返す"""
        if not 0 <= page_index < self.page_count:
            return None
        layout = self.layouts[page_index]
        if not 0 <= tile < layout.tile_count:
            return None
        left, top, right, bottom = layout.tile_rect(tile)
        # 表示座標 → 元ページの座標（左上原点）
        x0 = layout.clip[0] + left / layout.zoom
        y0 = layout.clip[1] + top / layout.zoom
        x1 = layout.clip[0] + right / layout.zoom
        y1 = layout.clip[1] + bottom / layout.zoom
        crop = (
            max(0.0, x0),
            max(0.0, layout.page_height - y1),
            max(0.0, layout.page_width - x1),
            max(0.0, y0),
        )
        scale = CSS_PX_PER_PT * RENDER_DENSITY * layout.zoom
        
        with PDFIUM_LOCK:
            if self._closed:
                return None
            page = self._doc[page_index]
            try:
                bitmap = page.render(scale=scale, crop=crop, may_draw_forms=True)
                image = bitmap.to_pil()
            finally:
                page.close()
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG", compress_level=3)
        return buffer.getvalue()
    
    # ------------------------------------------------------------------
    # マッチ箇所の検出
    # ------------------------------------------------------------------
    
    def find_hits(self, query: CompiledQuery, max_hits: int = 1000) -> tuple[list[PageHit], bool]:
        """全ページからマッチ箇所を探す
        
        Returns:
            (マッチ一覧, 上限で打ち切ったか)
        """
        hits: list[PageHit] = []
        for page_index in range(self.page_count):
            for hit in self._find_page_hits(page_index, query):
                if len(hits) >= max_hits:
                    return hits, True
                hits.append(hit)
        return hits, False
    
    def _find_page_hits(self, page_index: int, query: CompiledQuery) -> list[PageHit]:
        layout = self.layouts[page_index]
        with PDFIUM_LOCK:
            if self._closed:
                return []
            page = self._doc[page_index]
            try:
                blocks = page_blocks(page)
            finally:
                page.close()
        
        hits: list[PageHit] = []
        for block in blocks:
            text = block.text
            if not text or query.is_excluded(text):
                continue
            for start, end, _ in query.finditer(text):
                rects = [layout.to_display(r) for r in merge_rects(block.boxes[start:end])]
                if not rects:
                    continue
                hits.append(PageHit(
                    page=page_index,
                    rects=rects,
                    text=text[start:end],
                    before=text[max(0, start - CONTEXT_CHARS):start],
                    after=text[end:end + CONTEXT_CHARS],
                ))
        return hits
    
    # ------------------------------------------------------------------
    # Excel 用: シートの先頭ページの推定
    # ------------------------------------------------------------------
    
    def sheet_start_pages(self) -> list[int]:
        """各シートの先頭ページを推定する（行番号が 1 から始まるページ）"""
        starts = []
        for index in range(self.page_count):
            with PDFIUM_LOCK:
                if self._closed:
                    return []
                page = self._doc[index]
                try:
                    textpage = page.get_textpage()
                    try:
                        lines = page_lines(page, textpage)
                    finally:
                        textpage.close()
                finally:
                    page.close()
            numbers = [w for line in lines for w in _words(line) if w[0].isdigit()]
            if not numbers:
                continue
            first = min(numbers, key=lambda w: (round(w[1][1]), w[1][0]))
            if first[0] == "1":
                starts.append(index)
        return starts


def _words(line) -> list[tuple[str, Rect, float]]:
    """行を語に分ける: (文字列, 矩形, 文字サイズ)"""
    words: list[tuple[str, Rect, float]] = []
    chars: list[str] = []
    boxes: list[Rect] = []
    sizes: list[float] = []
    
    def flush() -> None:
        if chars and boxes:
            words.append((
                "".join(chars),
                (min(b[0] for b in boxes), min(b[1] for b in boxes),
                 max(b[2] for b in boxes), max(b[3] for b in boxes)),
                sizes[0],
            ))
        chars.clear()
        boxes.clear()
        sizes.clear()
    
    previous: Optional[Rect] = None
    for ch, box, size in zip(line.chars, line.boxes, line.sizes):
        if ch.isspace() or box is None:
            flush()
            previous = None
            continue
        if previous is not None and box[0] - previous[2] > (box[3] - box[1]) * 0.3:
            flush()
        chars.append(ch)
        boxes.append(box)
        sizes.append(size)
        previous = box
    flush()
    return words


def _content_layout(page, width: float, height: float) -> PageLayout:
    """内容のある範囲だけを切り出し、縮小出力を元の大きさに戻すレイアウト"""
    full = (0.0, 0.0, width, height)
    scale = 0.5
    image = page.render(scale=scale).to_pil().convert("L")
    # 白以外の画素がある範囲（= 何かが描かれている範囲）
    mask = image.point(lambda v: 255 if v < 248 else 0)
    bbox = mask.getbbox()
    if not bbox:
        return PageLayout(full, page_width=width, page_height=height)
    
    textpage = page.get_textpage()
    try:
        lines = page_lines(page, textpage)
    finally:
        textpage.close()
    zoom = _estimate_zoom(lines)
    
    margin = 6.0 / zoom
    clip = (
        max(0.0, bbox[0] / scale - margin),
        max(0.0, bbox[1] / scale - margin),
        min(width, bbox[2] / scale + margin),
        min(height, bbox[3] / scale + margin),
    )
    if clip[2] - clip[0] < 1 or clip[3] - clip[1] < 1:
        return PageLayout(full, page_width=width, page_height=height)
    return PageLayout(clip, zoom, width, height)


_DIGITS = re.compile(r"^\d+$")


def _estimate_zoom(lines) -> float:
    """縮小率の逆数を推定する
    
    行番号（1, 2, 3…）は標準の文字サイズで出力されるため、その大きさから
    「何倍に縮小されたか」を求める。行番号が見つからなければ等倍とする。
    """
    sizes: Counter = Counter()
    for line in lines:
        for text, _, size in _words(line):
            if _DIGITS.match(text) and size > 0:
                sizes[round(size, 1)] += 1
    if not sizes:
        return 1.0
    size = sizes.most_common(1)[0][0]
    zoom = SHEET_HEADING_FONT_PT / size
    # 等倍に近い場合は補正しない（フォント差による誤差で画像がぼやけるのを避ける）
    if zoom < 1.15:
        return 1.0
    return min(zoom, MAX_ZOOM)
