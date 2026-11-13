"""PDFページの文字と位置の取得（pypdfium2 / PDFium）

PDFium が返す文字と文字ごとの矩形から「行」「段落（ブロック）」を組み立てる。
検索用のテキスト抽出と、プレビューでのヒット位置の計算で同じ処理を使い、
両者の文字列が一致するようにしている。

座標はすべて「表示領域（CropBox）の左上を原点、下向きを正」とした pt 単位。
PDFium はスレッドセーフではないため、呼び出し側で PDFIUM_LOCK を取ること。
"""

import ctypes
import threading
from dataclasses import dataclass, field
from typing import Optional

from src.common.textnorm import line_separator

# PDFium の呼び出しを直列化するロック（プロセス内で共有）
PDFIUM_LOCK = threading.RLock()

Rect = tuple[float, float, float, float]


@dataclass
class TextLine:
    chars: list[str] = field(default_factory=list)
    boxes: list[Optional[Rect]] = field(default_factory=list)
    sizes: list[float] = field(default_factory=list)
    
    def bounds(self) -> Optional[Rect]:
        real = [b for b in self.boxes if b is not None]
        if not real:
            return None
        return (min(b[0] for b in real), min(b[1] for b in real),
                max(b[2] for b in real), max(b[3] for b in real))
    
    @property
    def text(self) -> str:
        return "".join(self.chars)
    
    def strip(self) -> "TextLine":
        start, end = 0, len(self.chars)
        while start < end and self.chars[start].isspace():
            start += 1
        while end > start and self.chars[end - 1].isspace():
            end -= 1
        return TextLine(self.chars[start:end], self.boxes[start:end], self.sizes[start:end])


@dataclass
class TextBlock:
    """段落相当のまとまり（text と boxes は1文字ずつ対応）"""
    text: str
    boxes: list[Optional[tuple[int, Rect]]]  # (行番号, 矩形)。行の継ぎ目に入れた文字は None
    lines: list[TextLine]


def page_geometry(page) -> tuple[float, float, float, float]:
    """表示領域（CropBox）: (左, 下, 右, 上) の PDF 座標"""
    left, bottom, right, top = page.get_cropbox()
    return float(left), float(bottom), float(right), float(top)


def page_lines(page, textpage) -> list[TextLine]:
    """ページの文字を行に分ける（PDFium の文字順のまま）"""
    import pypdfium2.raw as raw
    
    handle = textpage.raw
    count = raw.FPDFText_CountChars(handle)
    if count <= 0:
        return []
    
    left, bottom, right, top = page_geometry(page)
    text = textpage.get_text_range(0, count)
    if len(text) != count:
        # サロゲートペア等で文字数がずれる場合は1文字ずつ取得する
        text = "".join(chr(raw.FPDFText_GetUnicode(handle, i) or 0xFFFD) for i in range(count))
    
    x0, x1, y0, y1 = ctypes.c_double(), ctypes.c_double(), ctypes.c_double(), ctypes.c_double()
    get_box = raw.FPDFText_GetCharBox
    get_size = raw.FPDFText_GetFontSize
    
    lines: list[TextLine] = []
    line = TextLine()
    previous: Optional[Rect] = None
    
    def finish() -> None:
        nonlocal line
        stripped = line.strip()
        if stripped.chars:
            lines.append(stripped)
        line = TextLine()
    
    for i, ch in enumerate(text):
        if ch in "\r\n":
            finish()
            previous = None
            continue
        if ch == "\x00" or ch == "￾":
            continue
        box: Optional[Rect] = None
        if get_box(handle, i, ctypes.byref(x0), ctypes.byref(x1), ctypes.byref(y0), ctypes.byref(y1)):
            if x1.value > x0.value or y1.value > y0.value:
                box = (x0.value - left, top - y1.value, x1.value - left, top - y0.value)
        if box is not None and previous is not None and _starts_new_line(previous, box):
            finish()
        line.chars.append(ch)
        line.boxes.append(box)
        line.sizes.append(float(get_size(handle, i)))
        if box is not None:
            previous = box
    finish()
    return lines


def _starts_new_line(previous: Rect, box: Rect) -> bool:
    """改行文字が無くても、位置が大きく変わったら別の行とみなす"""
    height = max(previous[3] - previous[1], box[3] - box[1], 1.0)
    center_prev = (previous[1] + previous[3]) / 2
    center_box = (box[1] + box[3]) / 2
    if abs(center_box - center_prev) > height * 0.6:
        return True
    # 同じ高さでも、左へ戻る・大きく離れる場合は別の行（表の別のセルなど）
    if box[2] < previous[0] - height * 0.5:
        return True
    return box[0] - previous[2] > height * 3


def group_blocks(lines: list[TextLine]) -> list[TextBlock]:
    """近接して縦に並ぶ行を段落にまとめる"""
    blocks: list[list[TextLine]] = []
    previous_bounds: Optional[Rect] = None
    for line in lines:
        bounds = line.bounds()
        if blocks and previous_bounds is not None and bounds is not None and _continues(previous_bounds, bounds):
            blocks[-1].append(line)
        else:
            blocks.append([line])
        if bounds is not None:
            previous_bounds = bounds
    return [_make_block(group) for group in blocks]


def _continues(prev: Rect, cur: Rect) -> bool:
    height = max(prev[3] - prev[1], cur[3] - cur[1], 1.0)
    below = cur[1] >= prev[1] + height * 0.3
    gap = cur[1] - prev[3]
    overlap = cur[0] < prev[2] and cur[2] > prev[0]
    return below and gap < height * 0.8 and overlap


def _make_block(lines: list[TextLine]) -> TextBlock:
    chars: list[str] = []
    boxes: list[Optional[tuple[int, Rect]]] = []
    for index, line in enumerate(lines):
        if chars:
            separator = line_separator(chars[-1], line.chars[0])
            if separator:
                chars.append(separator)
                boxes.append(None)
        for ch, box in zip(line.chars, line.boxes):
            chars.append(ch)
            boxes.append((index, box) if box is not None else None)
    return TextBlock("".join(chars), boxes, lines)


def page_blocks(page) -> list[TextBlock]:
    """ページの段落一覧（呼び出し側で PDFIUM_LOCK を取ること）"""
    textpage = page.get_textpage()
    try:
        return group_blocks(page_lines(page, textpage))
    finally:
        textpage.close()


def merge_rects(boxes: list[Optional[tuple[int, Rect]]]) -> list[Rect]:
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


def open_document(path):
    """PDFを開く（パスワード付きは ValueError）"""
    import pypdfium2 as pdfium
    
    try:
        return pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as e:
        message = str(e)
        if "password" in message.lower():
            raise ValueError("パスワードで保護されたPDFです") from e
        raise ValueError(f"PDFを開けませんでした（{message}）") from e
