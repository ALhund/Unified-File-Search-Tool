"""プレビューレンダラーモジュール

プレビュー用のHTMLを組み立てる。表示方法は2種類:

- 原本表示（ページ表示）: ページ画像の上にマッチ箇所の矩形を重ねる
- テキスト表示: 抽出したテキストを表・行番号付きで再構成し、マッチ箇所を <mark> で囲む
"""

import html
import re
from dataclasses import dataclass, field
from typing import Optional

from src.extraction import ExtractedContent, ContentBlock
from src.extraction.base import KIND_LABELS
from src.preview.page_document import CSS_PX_PER_PT, PageDocument, PageHit
from src.search.query import CompiledQuery


@dataclass
class PreviewHit:
    """プレビュー上のマッチ箇所（ナビゲーション用）"""
    label: str  # 位置（例: "ページ 3"）
    text: str  # 前後を含む抜粋


@dataclass
class RenderedPreview:
    """プレビューの生成結果"""
    html: str = ""
    hits: list[PreviewHit] = field(default_factory=list)
    mode: str = "text"  # page / text
    page_document: Optional[PageDocument] = None
    truncated: bool = False  # マッチ箇所が上限で打ち切られた
    note: str = ""  # 利用者への補足（変換できなかった理由など）
    info: str = ""  # ファイル情報（作成者など）
    page_mode_available: bool = False
    sections: list[str] = field(default_factory=list)  # ページ/シート/スライドの見出し（ジャンプ用）


_COMMON_STYLE = """
:root {
    color-scheme: light;
    --bg: #E4E6EA; --surface: #FFFFFF; --surface-alt: #F7F8FA; --border: #E2E4E8;
    --text: #1A1C20; --text-2: #5B616B; --text-3: #8B919A;
    --mark: #FFE34D; --mark-border: #E8B400; --current: #FF9F1C; --current-ring: #E8590C;
    --label: #4A505A; --count-bg: #FFE34D; --count-text: #3A2A00; --shadow: rgba(0,0,0,0.16);
    --header: #F1F3F5;
}
html.dark {
    color-scheme: dark;
    --bg: #151517; --surface: #232326; --surface-alt: #2A2A2E; --border: #38383D;
    --text: #EDEDF0; --text-2: #B0B3BA; --text-3: #80848C;
    --mark: #F5C518; --mark-border: #B58E00; --label: #B0B3BA; --shadow: rgba(0,0,0,0.6);
    --header: #2C2C30;
}
* { box-sizing: border-box; }
html { scroll-padding: 80px; }
body {
    margin: 0;
    font-family: 'Segoe UI Variable Text', 'Segoe UI', 'Yu Gothic UI', 'Meiryo', 'Hiragino Sans', 'Noto Sans CJK JP', sans-serif;
    font-size: 14px;
    line-height: 1.6;
    color: var(--text);
    background: var(--bg);
}
::-webkit-scrollbar { width: 12px; height: 12px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(128,128,140,0.45); border-radius: 6px; border: 3px solid transparent; background-clip: content-box; }
::-webkit-scrollbar-thumb:hover { background-color: rgba(128,128,140,0.7); }
::-webkit-scrollbar-corner { background: transparent; }
@keyframes hit-pulse {
    0% { box-shadow: 0 0 0 0 rgba(255, 120, 30, 0.85); }
    100% { box-shadow: 0 0 0 16px rgba(255, 120, 30, 0); }
}
.empty { color: var(--text-3); padding: 32px; text-align: center; }
"""

_PAGE_STYLE = """
body { padding: 8px 20px 56px; }
.page-label {
    color: var(--label); font-size: 12px; margin: 16px auto 6px;
    display: flex; align-items: center; gap: 8px; font-weight: 600;
}
.page-label .count {
    background: var(--count-bg); color: var(--count-text); border-radius: 10px;
    padding: 0 8px; font-weight: 700; font-size: 11px;
}
.page {
    position: relative; margin: 0 auto; background: #fff;
    box-shadow: 0 1px 2px var(--shadow), 0 6px 22px var(--shadow); border-radius: 2px;
}
.page img { position: absolute; display: block; user-select: none; }
.hit {
    position: absolute; background: rgba(255, 227, 77, 0.55);
    mix-blend-mode: multiply; border-radius: 2px; cursor: pointer;
    outline: 1.5px solid rgba(232, 180, 0, 0.95);
}
.hit.current {
    background: rgba(255, 159, 28, 0.6); outline: 2.5px solid var(--current-ring);
    animation: hit-pulse 0.9s ease-out 2; z-index: 2;
}
"""

_TEXT_STYLE = """
body { padding: 16px 20px 56px; }
mark.hit {
    background: var(--mark); color: #1A1C20; border-radius: 3px;
    padding: 1px 1px; box-shadow: 0 0 0 1px var(--mark-border); cursor: pointer;
}
mark.hit.current {
    background: var(--current); box-shadow: 0 0 0 2px var(--current-ring);
    animation: hit-pulse 0.9s ease-out 2;
}
.section {
    background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
    margin: 0 0 16px; box-shadow: 0 1px 3px var(--shadow); overflow: hidden;
}
.section > .title {
    padding: 7px 14px; font-weight: 600; font-size: 13px; color: #fff;
    display: flex; gap: 8px; align-items: center;
}
.section > .body { padding: 12px 16px; overflow-x: auto; }
.section.page > .title { background: #3B6FD8; }
.section.sheet > .title { background: #1F7A4A; }
.section.slide > .title { background: #C2511F; }
.section.doc > .title { background: #2B5FB4; }
.title .count {
    background: var(--count-bg); color: var(--count-text); border-radius: 10px;
    padding: 0 8px; font-size: 11px; font-weight: 700;
}
p.block { margin: 0 0 8px; white-space: pre-wrap; overflow-wrap: anywhere; }
p.block.heading { font-size: 17px; font-weight: 700; margin-top: 12px; }
.box {
    border: 1px dashed var(--text-3); border-radius: 6px; background: var(--surface-alt);
    padding: 6px 10px; margin: 0 0 8px; white-space: pre-wrap; overflow-wrap: anywhere;
}
.box > .tag {
    display: inline-block; font-size: 11px; color: #fff; background: #6B7480;
    border-radius: 4px; padding: 0 6px; margin-right: 8px; vertical-align: 1px;
}
table.grid { border-collapse: collapse; font-size: 13px; margin: 0 0 8px; }
table.grid td, table.grid th {
    border: 1px solid var(--border); padding: 2px 8px; vertical-align: top;
    white-space: pre-wrap; max-width: 420px; overflow-wrap: anywhere; min-width: 48px;
}
table.grid th {
    background: var(--header); color: var(--text-2); font-weight: 500; text-align: center;
    min-width: 36px; position: sticky; top: 0;
}
table.grid th.row { position: sticky; left: 0; }
table.grid tr.gap td { border: none; color: var(--text-3); text-align: center; padding: 0; }
.code { display: flex; align-items: flex-start; font-family: 'Cascadia Mono', Consolas, 'BIZ UDGothic', 'MS Gothic', 'Noto Sans Mono CJK JP', monospace; font-size: 13px; line-height: 1.55; }
.code pre { margin: 0; font: inherit; white-space: pre; tab-size: 4; }
.code .gutter {
    position: sticky; left: 0; text-align: right; color: var(--text-3); background: var(--surface-alt);
    padding: 8px 10px; border-right: 1px solid var(--border); user-select: none;
}
.code .text { padding: 8px 12px; }
.section.code-section > .body { padding: 0; }
.encoding {
    position: fixed; right: 12px; bottom: 10px; background: rgba(0, 0, 0, 0.65);
    color: #fff; border-radius: 6px; padding: 2px 9px; font-size: 12px;
}
"""

_SCRIPT = """
function notify(kind, value) { document.title = kind + ':' + value + ':' + Date.now(); }
function gotoHit(index, smooth) {
    document.querySelectorAll('.hit.current').forEach(function (e) { e.classList.remove('current'); });
    var parts = document.querySelectorAll('.hit[data-hit="' + index + '"]');
    if (!parts.length) { return false; }
    parts.forEach(function (e) { e.classList.add('current'); });
    parts[0].scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'center', inline: 'center' });
    return true;
}
function gotoSection(index) {
    var target = document.querySelector('[data-section="' + index + '"]');
    if (target) { target.scrollIntoView({ behavior: 'auto', block: 'start' }); }
}
function contentWidth() {
    var width = 0;
    document.querySelectorAll('.page').forEach(function (e) { width = Math.max(width, e.offsetWidth); });
    return width;
}
function setDark(dark) { document.documentElement.classList.toggle('dark', !!dark); }
document.addEventListener('click', function (event) {
    var hit = event.target.closest('.hit');
    if (hit) { notify('hit', hit.dataset.hit); }
});
(function () {
    var current = -1, ticking = false;
    function update() {
        ticking = false;
        var sections = document.querySelectorAll('[data-section]');
        var best = 0, line = window.innerHeight * 0.35;
        for (var i = 0; i < sections.length; i++) {
            if (sections[i].getBoundingClientRect().top <= line) { best = i; } else { break; }
        }
        if (sections.length && best !== current) { current = best; notify('sec', sections[best].dataset.section); }
    }
    window.addEventListener('scroll', function () {
        if (!ticking) { ticking = true; window.requestAnimationFrame(update); }
    }, { passive: true });
    window.addEventListener('load', update);
})();
"""


def _document(style: str, body: str) -> str:
    return (
        "<!DOCTYPE html>\n<html lang='ja'><head><meta charset='utf-8'>"
        f"<style>{_COMMON_STYLE}{style}</style></head>\n<body>\n{body}\n"
        f"<script>{_SCRIPT}</script></body></html>"
    )


_CELL_RE = re.compile(r"^([A-Z]+)(\d+)$")
MAX_GRID_ROWS = 2000
MAX_GRID_COLS = 100
MAX_TEXT_LINES = 200_000




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


class PreviewRenderer:
    """プレビューレンダラー"""
    
    def __init__(self):
        # 直前に描画したテキスト表示のセクション見出し（ジャンプ用）
        self.last_sections: list[str] = []
    
    # ------------------------------------------------------------------
    # 原本表示（ページ画像 + マッチ箇所の重ね合わせ）
    # ------------------------------------------------------------------
    
    def render_pages(
        self,
        document: PageDocument,
        hits: list[PageHit],
        tile_url_prefix: str,
    ) -> tuple[str, list[PreviewHit]]:
        """ページ表示のHTMLを生成
        
        Args:
            document: 表示する文書
            hits: マッチ箇所
            tile_url_prefix: タイル画像URLの接頭辞（"<prefix>/<ページ>/<タイル>.png"）
        """
        hits_by_page: dict[int, list[tuple[int, PageHit]]] = {}
        for index, hit in enumerate(hits):
            hits_by_page.setdefault(hit.page, []).append((index, hit))
        
        parts: list[str] = []
        for page_index, layout in enumerate(document.layouts):
            width = layout.width * CSS_PX_PER_PT
            height = layout.height * CSS_PX_PER_PT
            page_hits = hits_by_page.get(page_index, [])
            
            count = f"<span class='count'>{len(page_hits)}件</span>" if page_hits else ""
            parts.append(
                f"<div class='page-label' data-section='{page_index}' style='width:{width:.1f}px'>"
                f"{html.escape(document.labels[page_index])}{count}</div>"
            )
            parts.append(
                f"<div class='page' id='page-{page_index}' "
                f"style='width:{width:.1f}px;height:{height:.1f}px'>"
            )
            for tile in range(layout.tile_count):
                left, top, right, bottom = (v * CSS_PX_PER_PT for v in layout.tile_rect(tile))
                parts.append(
                    f"<img loading='lazy' decoding='async' draggable='false' alt='' "
                    f"src='{tile_url_prefix}/{page_index}/{tile}.png' "
                    f"style='left:{left:.2f}px;top:{top:.2f}px;"
                    f"width:{right - left:.2f}px;height:{bottom - top:.2f}px'>"
                )
            for index, hit in page_hits:
                title = html.escape(hit.text, quote=True)
                for x0, y0, x1, y1 in hit.rects:
                    # 文字より少し大きく塗る（ページ寸法に対する割合で指定）
                    left = max(0.0, (x0 - 1.0) / layout.width * 100)
                    top = max(0.0, (y0 - 0.5) / layout.height * 100)
                    w = (x1 - x0 + 2.0) / layout.width * 100
                    h = (y1 - y0 + 1.0) / layout.height * 100
                    parts.append(
                        f"<div class='hit' data-hit='{index}' title='{title}' "
                        f"style='left:{left:.3f}%;top:{top:.3f}%;width:{w:.3f}%;height:{h:.3f}%'></div>"
                    )
            parts.append("</div>")
        
        if not document.layouts:
            parts.append("<div class='empty' style='color:#ddd'>表示できるページがありません</div>")
        
        preview_hits = [
            PreviewHit(document.labels[hit.page], _snippet(hit.before, hit.text, hit.after))
            for hit in hits
        ]
        return _document(_PAGE_STYLE, "\n".join(parts)), preview_hits
    
    # ------------------------------------------------------------------
    # テキスト表示
    # ------------------------------------------------------------------
    
    def render_text(
        self,
        content: ExtractedContent,
        query: Optional[CompiledQuery],
        max_hits: int = 1000,
    ) -> tuple[str, list[PreviewHit], bool]:
        """テキスト表示のHTMLを生成
        
        Returns:
            (HTML, マッチ箇所, 上限で打ち切ったか)
        """
        state = _HitState(query, max_hits)
        self.last_sections = []
        
        if content.total_lines is not None:
            body = self._render_plain_text(content, state)
        else:
            body = self._render_blocks(content, state)
        
        if not content.blocks:
            body += "<div class='empty'>表示できるテキストがありません</div>"
        if content.encoding:
            body += f"<div class='encoding'>{html.escape(content.encoding)}</div>"
        
        return _document(_TEXT_STYLE, body), state.hits, state.truncated
    
    def _render_plain_text(self, content: ExtractedContent, state: "_HitState") -> str:
        """テキストファイル: 行番号付きで元の行構成のまま表示"""
        total = min(content.total_lines or 0, MAX_TEXT_LINES)
        lines = [""] * total
        for block in content.blocks:
            if block.line is not None and 1 <= block.line <= total:
                lines[block.line - 1] = state.mark(block, f"行 {block.line}")
        
        gutter = "\n".join(str(n) for n in range(1, total + 1))
        note = ""
        if (content.total_lines or 0) > total:
            note = f"<div class='empty'>先頭 {total:,} 行のみ表示しています</div>"
        return (
            "<div class='section doc code-section' data-section='0'>"
            f"<div class='title'>{html.escape(content.file_path.name)}</div>"
            "<div class='body'><div class='code'>"
            f"<pre class='gutter'>{gutter}</pre><pre class='text'>{chr(10).join(lines)}</pre>"
            f"</div></div></div>{note}"
        )
    
    def _render_blocks(self, content: ExtractedContent, state: "_HitState") -> str:
        """ページ/シート/スライド単位にまとめて表示"""
        # 並び順を保ったままセクションに分ける
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
            else:
                existing = next((s for s in sections if s[1] == title), None) if key == "sheet" else None
                if existing:
                    existing[2].append(block)
                else:
                    sections.append((key, title, [block]))
        
        parts: list[str] = []
        self.last_sections = [title for _, title, _ in sections]
        for section_index, (key, title, blocks) in enumerate(sections):
            before = len(state.hits)
            if key == "sheet":
                body = self._render_sheet(blocks, state, title)
            else:
                body = self._render_flow(blocks, state, title if key != "doc" else "")
            found = len(state.hits) - before
            count = f"<span class='count'>{found}件</span>" if found else ""
            parts.append(
                f"<div class='section {key}' data-section='{section_index}'>"
                f"<div class='title'>{html.escape(title)}{count}</div>"
                f"<div class='body'>{body}</div></div>"
            )
        return "\n".join(parts)
    
    def _render_flow(self, blocks: list[ContentBlock], state: "_HitState", where: str) -> str:
        """段落・表・図形などを上から順に並べる"""
        parts: list[str] = []
        index = 0
        while index < len(blocks):
            block = blocks[index]
            
            if block.table is not None:
                # 同じ表のセルをまとめて表として描く
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
                parts.append("<table class='grid'>")
                for r in range(rows):
                    parts.append(
                        "<tr>" + "".join(f"<td>{cells.get((r, c), '')}</td>" for c in range(cols)) + "</tr>"
                    )
                parts.append("</table>")
                continue
            
            label = _join(where, KIND_LABELS.get(block.kind or "", ""))
            if block.kind in KIND_LABELS:
                parts.append(
                    f"<div class='box'><span class='tag'>{KIND_LABELS[block.kind]}</span>"
                    f"{state.mark(block, label)}</div>"
                )
            else:
                css = "block heading" if block.kind == "heading" else "block"
                parts.append(f"<p class='{css}'>{state.mark(block, label or '本文')}</p>")
            index += 1
        return "\n".join(parts)
    
    def _render_sheet(self, blocks: list[ContentBlock], state: "_HitState", where: str) -> str:
        """Excelシート: セルを行列の位置どおりに並べた表 + 図形の一覧"""
        cells: dict[tuple[int, int], ContentBlock] = {}
        extras: list[ContentBlock] = []
        for block in blocks:
            m = _CELL_RE.match(block.cell or "") if block.kind is None else None
            if m:
                cells[(int(m.group(2)), _column_index(m.group(1)))] = block
            else:
                extras.append(block)
        
        parts: list[str] = []
        if cells:
            max_row = max(r for r, _ in cells)
            max_col = min(max(c for _, c in cells), MAX_GRID_COLS)
            # 行数が多いシートは、値のある行だけを表示する
            if max_row <= MAX_GRID_ROWS:
                rows = list(range(1, max_row + 1))
            else:
                rows = sorted({r for r, _ in cells})[:MAX_GRID_ROWS]
            
            headers = "".join(f"<th>{_column_letters(c)}</th>" for c in range(1, max_col + 1))
            parts.append(f"<table class='grid'><tr><th></th>{headers}</tr>")
            previous = 0
            for r in rows:
                if r != previous + 1:
                    parts.append(f"<tr class='gap'><td colspan='{max_col + 1}'>⋮</td></tr>")
                previous = r
                row_html = [f"<tr><th class='row'>{r}</th>"]
                for c in range(1, max_col + 1):
                    block = cells.get((r, c))
                    row_html.append(
                        f"<td>{state.mark(block, _join(where, 'セル ' + block.cell)) if block else ''}</td>"
                    )
                row_html.append("</tr>")
                parts.append("".join(row_html))
            parts.append("</table>")
        
        for block in extras:
            tag = KIND_LABELS.get(block.kind or "", "図形")
            position = f"（{block.cell} 付近）" if block.cell else ""
            parts.append(
                f"<div class='box'><span class='tag'>{tag}{position}</span>"
                f"{state.mark(block, _join(where, tag))}</div>"
            )
        return "\n".join(parts)


def _join(*parts: str) -> str:
    return ", ".join(p for p in parts if p)


class _HitState:
    """テキスト表示でのマッチ箇所の採番と <mark> 付け"""
    
    def __init__(self, query: Optional[CompiledQuery], max_hits: int):
        self.query = query
        self.max_hits = max_hits
        self.hits: list[PreviewHit] = []
        self.truncated = False
    
    def mark(self, block: ContentBlock, label: str) -> str:
        """ブロックのテキストをエスケープし、マッチ箇所を <mark> で囲む"""
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
            out.append(html.escape(text[position:start]))
            out.append(
                f"<mark class='hit' data-hit='{len(self.hits)}'>{html.escape(text[start:end])}</mark>"
            )
            self.hits.append(PreviewHit(
                label,
                _snippet(text[max(0, start - 30):start], text[start:end], text[end:end + 30]),
            ))
            position = end
        out.append(html.escape(text[position:]))
        return "".join(out)
