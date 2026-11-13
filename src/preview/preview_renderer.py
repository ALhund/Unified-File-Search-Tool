"""プレビューの内容を組み立てる

表示方法は3種類（画面側の部品は src/ui/widgets/page_view.py, text_views.py）:

- page  … 原本表示。ページ画像の上にマッチ箇所の矩形を重ねる（PageDocument と PageHit）
- rich  … Office/PDF のテキスト表示。Qt のリッチテキスト（HTML の一部）で表やシートを再構成する
- plain … テキストファイル。行番号つきでそのまま表示し、マッチ箇所の位置（文字位置）を渡す

リッチテキストの色は @@名前@@ の形で書き、画面側がテーマの色に置き換える（テーマ切替に追従するため）。
"""

import html
import re
from dataclasses import dataclass, field
from typing import Optional

from src.extraction import ExtractedContent, ContentBlock
from src.extraction.base import KIND_LABELS
from src.preview.page_document import PageDocument, PageHit
from src.search.query import CompiledQuery

_CELL_RE = re.compile(r"^([A-Z]+)(\d+)$")
MAX_GRID_ROWS = 2000
MAX_GRID_COLS = 100
MAX_TEXT_LINES = 200_000
CONTEXT = 30

# リッチテキストで使う色の名前（画面側で置き換える）
COLOR_TOKENS = ("TEXT", "TEXT2", "TEXT3", "SURFACE", "SURFACE_ALT", "BORDER", "HEADER", "MARK", "MARK_TEXT")
SECTION_COLORS = {"page": "#3B6FD8", "sheet": "#1F7A4A", "slide": "#C2511F", "doc": "#2B5FB4"}


@dataclass
class PreviewHit:
    """プレビュー上のマッチ箇所（ナビゲーション用）"""
    label: str  # 位置（例: "ページ 3"）
    text: str  # 前後を含む抜粋


@dataclass
class RenderedPreview:
    """プレビューの生成結果"""
    mode: str = "rich"  # page / rich / plain
    hits: list[PreviewHit] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)  # ページ/シート/スライドの見出し（ジャンプ用）
    # page
    page_document: Optional[PageDocument] = None
    page_hits: list[PageHit] = field(default_factory=list)
    # rich
    html: str = ""
    # plain
    plain_text: str = ""
    plain_hits: list[tuple[int, int]] = field(default_factory=list)  # 文字位置 [開始, 終了)
    encoding: str = ""
    # 共通
    truncated: bool = False  # マッチ箇所が上限で打ち切られた
    note: str = ""  # 利用者への補足（変換できなかった理由など）
    info: str = ""  # ファイル情報（作成者など）
    page_mode_available: bool = False


def _snippet(before: str, text: str, after: str) -> str:
    return " ".join(f"{before}【{text}】{after}".split())


def _column_index(letters: str) -> int:
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch) - 64)
    return index


def _column_letters(index: int) -> str:
    letters = ""
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _join(*parts: str) -> str:
    return ", ".join(p for p in parts if p)


class PreviewRenderer:
    """テキスト表示の内容を組み立てる"""
    
    def __init__(self):
        # 直前に組み立てたリッチテキストのセクション見出し（ジャンプ用）
        self.last_sections: list[str] = []
    
    # ------------------------------------------------------------------
    # 原本表示
    # ------------------------------------------------------------------
    
    @staticmethod
    def page_hit_labels(document: PageDocument, hits: list[PageHit]) -> list[PreviewHit]:
        return [PreviewHit(document.labels[h.page], _snippet(h.before, h.text, h.after)) for h in hits]
    
    # ------------------------------------------------------------------
    # テキストファイル
    # ------------------------------------------------------------------
    
    def render_plain(
        self, content: ExtractedContent, query: Optional[CompiledQuery], max_hits: int = 1000
    ) -> tuple[str, list[tuple[int, int]], list[PreviewHit], bool]:
        """行番号どおりの全文と、マッチ箇所の文字位置
        
        Returns:
            (全文, マッチ位置, マッチ一覧, 上限で打ち切ったか)
        """
        total = min(content.total_lines or 0, MAX_TEXT_LINES)
        lines = [""] * total
        for block in content.blocks:
            if block.line is not None and 1 <= block.line <= total:
                lines[block.line - 1] = block.text
        
        spans: list[tuple[int, int]] = []
        hits: list[PreviewHit] = []
        truncated = False
        offset = 0
        for number, line in enumerate(lines, start=1):
            if query is not None and line and not truncated and not query.is_excluded(line):
                position = 0
                for start, end, _ in query.finditer(line):
                    if start < position:
                        continue
                    if len(spans) >= max_hits:
                        truncated = True
                        break
                    spans.append((offset + start, offset + end))
                    hits.append(PreviewHit(
                        f"行 {number}",
                        _snippet(line[max(0, start - CONTEXT):start], line[start:end], line[end:end + CONTEXT]),
                    ))
                    position = end
            offset += len(line) + 1  # 改行の分
        return "\n".join(lines), spans, hits, truncated
    
    # ------------------------------------------------------------------
    # Office / PDF のテキスト表示
    # ------------------------------------------------------------------
    
    def render_text(
        self,
        content: ExtractedContent,
        query: Optional[CompiledQuery],
        max_hits: int = 1000,
    ) -> tuple[str, list[PreviewHit], bool]:
        """リッチテキスト（HTML）を組み立てる
        
        マッチ箇所は <a name="hit-N" href="hit:N"> で囲む（画面側が位置を調べて強調・移動する）。
        
        Returns:
            (HTML, マッチ一覧, 上限で打ち切ったか)
        """
        state = _HitState(query, max_hits)
        self.last_sections = []
        body = self._render_blocks(content, state)
        if not content.blocks:
            body += "<p style='color:@@TEXT3@@'>表示できるテキストがありません</p>"
        document = (
            "<html><body style='color:@@TEXT@@; background-color:@@SURFACE@@'>"
            f"{body}</body></html>"
        )
        return document, state.hits, state.truncated
    
    def _render_blocks(self, content: ExtractedContent, state: "_HitState") -> str:
        """ページ/シート/スライド単位にまとめて表示"""
        sections: list[tuple[str, str, list[ContentBlock]]] = []
        for block in content.blocks:
            if block.sheet is not None:
                key, title = "sheet", f"シート: {block.sheet}"
            elif block.slide is not None:
                key, title = "slide", f"スライド {block.slide}"
            elif block.page is not None:
                key, title = "page", f"ページ {block.page}"
            else:
                key, title = "doc", content.file_path.name
            if sections and sections[-1][1] == title:
                sections[-1][2].append(block)
                continue
            existing = next((s for s in sections if s[1] == title), None) if key == "sheet" else None
            if existing:
                existing[2].append(block)
            else:
                sections.append((key, title, [block]))
        
        self.last_sections = [title for _, title, _ in sections]
        parts: list[str] = []
        for index, (key, title, blocks) in enumerate(sections):
            before = len(state.hits)
            if key == "sheet":
                body = self._render_sheet(blocks, state, title)
            else:
                body = self._render_flow(blocks, state, title if key != "doc" else "")
            found = len(state.hits) - before
            count = f"　<span style='color:#FFE9A8'>{found}件</span>" if found else ""
            parts.append(
                f"<a name='sec-{index}'></a>"
                f"<table width='100%' cellspacing='0' cellpadding='6' style='margin-top:{14 if index else 0}px'>"
                f"<tr><td bgcolor='{SECTION_COLORS[key]}' style='color:#FFFFFF; font-weight:600'>"
                f"{html.escape(title)}{count}</td></tr></table>"
                f"<div style='margin:8px 4px 0 4px'>{body}</div>"
            )
        return "\n".join(parts)
    
    def _render_flow(self, blocks: list[ContentBlock], state: "_HitState", where: str) -> str:
        """段落・表・図形などを上から順に並べる"""
        parts: list[str] = []
        index = 0
        while index < len(blocks):
            block = blocks[index]
            
            if block.table is not None:
                table_id = block.table[0]
                cells: dict[tuple[int, int], str] = {}
                while (
                    index < len(blocks)
                    and blocks[index].table is not None
                    and blocks[index].table[0] == table_id
                ):
                    cell = blocks[index]
                    cells[(cell.table[1], cell.table[2])] = state.mark(cell, _join(where, "表"))
                    index += 1
                rows = max(r for r, _ in cells) + 1
                cols = max(c for _, c in cells) + 1
                parts.append(_GRID_OPEN)
                for r in range(rows):
                    parts.append(
                        "<tr>" + "".join(
                            f"<td style='{_CELL_STYLE}'>{cells.get((r, c), '')}</td>" for c in range(cols)
                        ) + "</tr>"
                    )
                parts.append("</table>")
                continue
            
            label = _join(where, KIND_LABELS.get(block.kind or "", ""))
            text = state.mark(block, label or "本文")
            if block.kind in KIND_LABELS:
                parts.append(_box(KIND_LABELS[block.kind], text))
            elif block.kind == "heading":
                parts.append(f"<p style='font-size:large; font-weight:700; margin-top:10px; white-space:pre-wrap'>{text}</p>")
            else:
                parts.append(f"<p style='white-space:pre-wrap; margin:0 0 6px 0'>{text}</p>")
            index += 1
        return "\n".join(parts)
    
    def _render_sheet(self, blocks: list[ContentBlock], state: "_HitState", where: str) -> str:
        """Excelシート: セルを行列の位置どおりに並べた表 + 図形の一覧"""
        cells: dict[tuple[int, int], ContentBlock] = {}
        extras: list[ContentBlock] = []
        for block in blocks:
            match = _CELL_RE.match(block.cell or "") if block.kind is None else None
            if match:
                cells[(int(match.group(2)), _column_index(match.group(1)))] = block
            else:
                extras.append(block)
        
        parts: list[str] = []
        if cells:
            max_row = max(r for r, _ in cells)
            max_col = min(max(c for _, c in cells), MAX_GRID_COLS)
            if max_row <= MAX_GRID_ROWS:
                rows = list(range(1, max_row + 1))
            else:
                rows = sorted({r for r, _ in cells})[:MAX_GRID_ROWS]
            
            header = f"<td style='{_HEAD_STYLE}'></td>" + "".join(
                f"<td style='{_HEAD_STYLE}' align='center'>{_column_letters(c)}</td>" for c in range(1, max_col + 1)
            )
            parts.append(_GRID_OPEN + f"<tr>{header}</tr>")
            previous = 0
            for r in range(len(rows)):
                row = rows[r]
                if row != previous + 1:
                    parts.append(f"<tr><td colspan='{max_col + 1}' align='center' style='color:@@TEXT3@@'>⋮</td></tr>")
                previous = row
                line = [f"<tr><td style='{_HEAD_STYLE}' align='right'>{row}</td>"]
                for c in range(1, max_col + 1):
                    block = cells.get((row, c))
                    value = state.mark(block, _join(where, "セル " + block.cell)) if block else ""
                    line.append(f"<td style='{_CELL_STYLE}'>{value}</td>")
                line.append("</tr>")
                parts.append("".join(line))
            parts.append("</table>")
        
        for block in extras:
            tag = KIND_LABELS.get(block.kind or "", "図形")
            position = f"（{block.cell} 付近）" if block.cell else ""
            parts.append(_box(tag + position, state.mark(block, _join(where, tag))))
        return "\n".join(parts)


_GRID_OPEN = "<table cellspacing='0' cellpadding='3' border='1' style='border-color:@@BORDER@@; border-collapse:collapse; margin:4px 0 8px 0'>"
_CELL_STYLE = "white-space:pre-wrap; border-color:@@BORDER@@"
_HEAD_STYLE = "background-color:@@HEADER@@; color:@@TEXT2@@; border-color:@@BORDER@@"


def _box(tag: str, text: str) -> str:
    return (
        "<table width='100%' cellspacing='0' cellpadding='6' style='margin:4px 0 8px 0'>"
        f"<tr><td bgcolor='@@SURFACE_ALT@@' style='white-space:pre-wrap'>"
        f"<span style='background-color:#6B7480; color:#FFFFFF'>&nbsp;{html.escape(tag)}&nbsp;</span>　{text}"
        "</td></tr></table>"
    )


class _HitState:
    """テキスト表示でのマッチ箇所の採番と強調"""
    
    def __init__(self, query: Optional[CompiledQuery], max_hits: int):
        self.query = query
        self.max_hits = max_hits
        self.hits: list[PreviewHit] = []
        self.truncated = False
    
    def mark(self, block: ContentBlock, label: str) -> str:
        """ブロックのテキストをエスケープし、マッチ箇所を強調表示用のアンカーで囲む"""
        text = block.text
        if self.query is None or self.query.is_excluded(text):
            return html.escape(text)
        
        out: list[str] = []
        position = 0
        for start, end, _ in self.query.finditer(text):
            if start < position:
                continue
            if len(self.hits) >= self.max_hits:
                self.truncated = True
                break
            index = len(self.hits)
            out.append(html.escape(text[position:start]))
            out.append(
                f"<a name='hit-{index}' href='hit:{index}' style='background-color:@@MARK@@; "
                f"color:@@MARK_TEXT@@; text-decoration:none'>{html.escape(text[start:end])}</a>"
            )
            self.hits.append(PreviewHit(
                label,
                _snippet(text[max(0, start - CONTEXT):start], text[start:end], text[end:end + CONTEXT]),
            ))
            position = end
        out.append(html.escape(text[position:]))
        return "".join(out)
