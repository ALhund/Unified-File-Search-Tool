"""ページ画像によるプレビュー（PDF / PDFへ変換したOfficeファイル）

PyMuPDFでページを画像化し、検索語の位置（矩形）を文字単位の座標から求める。
画像の上に矩形を重ねることで、元のレイアウトを崩さずにマッチ箇所を強調できる。
"""

import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.common.textnorm import join_wrapped_lines, line_separator
from src.common.utils import FITZ_LOCK
from src.search.query import CompiledQuery

# 1pt（1/72インチ）あたりのCSSピクセル数
CSS_PX_PER_PT = 96 / 72
# 画面表示より高精細に描画する倍率（ズームしても文字がぼやけにくい）
RENDER_DENSITY = 1.5
# タイル1枚の最大サイズ（表示上のpt）。巨大なシートは縦横に分割して必要な部分だけ描画する
TILE_WIDTH_PT = 1300.0
TILE_HEIGHT_PT = 1100.0
CONTEXT_CHARS = 30
# Excelの行列番号の標準的な文字サイズ（縮小率の推定に使う）
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
    
    元ページのうち clip の範囲を zoom 倍して表示する。
    （Excelは用紙に収めるため縮小出力されるので、余白を切り落として元の大きさに戻す）
    """
    clip: Rect  # 表示する範囲（元ページの座標, pt）
    zoom: float = 1.0
    
    def __post_init__(self):
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
        import pymupdf as fitz
        
        self.pdf_path = Path(pdf_path)
        self._closed = False
        with FITZ_LOCK:
            self._doc = fitz.open(str(self.pdf_path))
            if self._doc.needs_pass:
                self._doc.close()
                raise ValueError("パスワードで保護されたPDFです")
            self.layouts: list[PageLayout] = []
            for page in self._doc:
                if page.rotation:
                    page.remove_rotation()
                rect = page.rect
                clip = (rect.x0, rect.y0, rect.x1, rect.y1)
                if fit_to_content:
                    self.layouts.append(_content_layout(page, clip))
                else:
                    self.layouts.append(PageLayout(clip))
        
        if labels and len(labels) == len(self.layouts):
            self.labels = labels
        else:
            self.labels = [f"ページ {i + 1}" for i in range(len(self.layouts))]
    
    @property
    def page_count(self) -> int:
        return len(self.layouts)
    
    def sheet_start_pages(self) -> list[int]:
        """Excel用: 各シートの先頭ページを推定する（行番号が 1 から始まるページ）"""
        starts = []
        for index in range(self.page_count):
            with FITZ_LOCK:
                if self._closed:
                    return []
                words = self._doc[index].get_text("words")
            numbers = [w for w in words if w[4].isdigit()]
            if not numbers:
                continue
            first = min(numbers, key=lambda w: (round(w[1]), w[0]))
            if first[4] == "1":
                starts.append(index)
        return starts
    
    def close(self) -> None:
        with FITZ_LOCK:
            if not self._closed:
                self._closed = True
                self._doc.close()
    
    # ------------------------------------------------------------------
    # 描画
    # ------------------------------------------------------------------
    
    def render_tile(self, page_index: int, tile: int) -> Optional[bytes]:
        """ページの一部（タイル）をPNGで返す"""
        import pymupdf as fitz
        
        if not 0 <= page_index < self.page_count:
            return None
        layout = self.layouts[page_index]
        if not 0 <= tile < layout.tile_count:
            return None
        left, top, right, bottom = layout.tile_rect(tile)
        x0, y0 = layout.clip[0], layout.clip[1]
        clip = fitz.Rect(
            x0 + left / layout.zoom,
            y0 + top / layout.zoom,
            x0 + right / layout.zoom,
            y0 + bottom / layout.zoom,
        )
        scale = CSS_PX_PER_PT * RENDER_DENSITY * layout.zoom
        
        with FITZ_LOCK:
            if self._closed:
                return None
            pixmap = self._doc[page_index].get_pixmap(
                matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False
            )
            return pixmap.tobytes("png")
    
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
            if not self._page_may_match(page_index, query):
                continue
            for hit in self._find_page_hits(page_index, query):
                if len(hits) >= max_hits:
                    return hits, True
                hits.append(hit)
        return hits, False
    
    def _page_may_match(self, page_index: int, query: CompiledQuery) -> bool:
        """軽い抽出で先に判定し、マッチのないページは文字座標の取得を省く"""
        with FITZ_LOCK:
            if self._closed:
                return False
            blocks = self._doc[page_index].get_text("blocks")
        for block in blocks:
            if block[6] != 0:
                continue
            text = join_wrapped_lines([line.strip() for line in block[4].split("\n")])
            if text and next(query.finditer(text), None) is not None:
                return True
        return False
    
    def _find_page_hits(self, page_index: int, query: CompiledQuery) -> list[PageHit]:
        import pymupdf as fitz
        
        layout = self.layouts[page_index]
        with FITZ_LOCK:
            if self._closed:
                return []
            flags = fitz.TEXT_PRESERVE_LIGATURES | fitz.TEXT_PRESERVE_WHITESPACE
            raw = self._doc[page_index].get_text("rawdict", flags=flags, sort=True)
        
        hits: list[PageHit] = []
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            
            text, boxes = _block_chars(block)
            if not text or query.is_excluded(text):
                continue
            
            for start, end, _ in query.finditer(text):
                rects = [layout.to_display(r) for r in _merge_rects(boxes[start:end])]
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


def _content_layout(page, page_rect: Rect) -> PageLayout:
    """内容のある範囲だけを切り出し、縮小出力を元の大きさに戻すレイアウト"""
    boxes = [item[1] for item in page.get_bboxlog()]
    if not boxes:
        return PageLayout(page_rect)
    
    zoom = _estimate_zoom(page)
    margin = 6.0 / zoom
    clip = (
        max(page_rect[0], min(b[0] for b in boxes) - margin),
        max(page_rect[1], min(b[1] for b in boxes) - margin),
        min(page_rect[2], max(b[2] for b in boxes) + margin),
        min(page_rect[3], max(b[3] for b in boxes) + margin),
    )
    if clip[2] - clip[0] < 1 or clip[3] - clip[1] < 1:
        return PageLayout(page_rect)
    return PageLayout(clip, zoom)


def _estimate_zoom(page) -> float:
    """縮小率の逆数を推定する
    
    行番号（1, 2, 3…）は標準の文字サイズで出力されるため、その大きさから
    「何倍に縮小されたか」を求める。行番号が見つからなければ等倍とする。
    """
    sizes: Counter = Counter()
    for block in page.get_text("dict", flags=0).get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span.get("text", "").strip().isdigit():
                    sizes[round(span.get("size", 0), 1)] += 1
    if not sizes:
        return 1.0
    size = sizes.most_common(1)[0][0]
    if size <= 0:
        return 1.0
    zoom = SHEET_HEADING_FONT_PT / size
    # 等倍に近い場合は補正しない（フォント差による誤差で画像がぼやけるのを避ける）
    if zoom < 1.15:
        return 1.0
    return min(zoom, MAX_ZOOM)


def _block_chars(block: dict) -> tuple[str, list[Optional[tuple[int, Rect]]]]:
    """テキストブロックを「文字列」と「各文字の(行番号, 矩形)」に展開する
    
    行の継ぎ目は抽出時（PdfExtractor）と同じ規則で連結する。
    """
    chars: list[str] = []
    boxes: list[Optional[tuple[int, Rect]]] = []
    
    for line_index, line in enumerate(block.get("lines", [])):
        line_chars = [
            (ch["c"], tuple(ch["bbox"]))
            for span in line.get("spans", [])
            for ch in span.get("chars", [])
        ]
        # 行頭・行末の空白は除く
        while line_chars and line_chars[0][0].isspace():
            line_chars.pop(0)
        while line_chars and line_chars[-1][0].isspace():
            line_chars.pop()
        if not line_chars:
            continue
        
        if chars:
            separator = line_separator(chars[-1], line_chars[0][0])
            if separator:
                chars.append(separator)
                boxes.append(None)
        
        for c, bbox in line_chars:
            # 合字などで複数文字になる場合も、文字数と矩形の数をそろえる
            for piece in c:
                chars.append(piece)
                boxes.append((line_index, bbox))
    
    return "".join(chars), boxes


def _merge_rects(boxes: list[Optional[tuple[int, Rect]]]) -> list[Rect]:
    """文字ごとの矩形を行単位にまとめる"""
    merged: dict[int, list[float]] = {}
    for item in boxes:
        if item is None:
            continue
        line_index, (x0, y0, x1, y1) = item
        if line_index in merged:
            rect = merged[line_index]
            rect[0] = min(rect[0], x0)
            rect[1] = min(rect[1], y0)
            rect[2] = max(rect[2], x1)
            rect[3] = max(rect[3], y1)
        else:
            merged[line_index] = [x0, y0, x1, y1]
    return [tuple(r) for r in merged.values()]
