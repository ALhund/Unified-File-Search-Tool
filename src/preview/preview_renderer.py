"""プレビューレンダラーモジュール。

ファイル内容を HTML 形式でレンダリングし、マッチ箇所を強調表示する。
ファイル種別（Word / Excel / PowerPoint / PDF / テキスト / Markdown）ごとに
それぞれのドキュメントらしい見た目でプレビューを生成する。

各 Office 形式はリッチレンダリング（ファイルを再読み込みして書式情報を抽出）を
試みる。失敗時はテキストのみの簡易レンダリングにフォールバックする。
"""

import html
import re
from pathlib import Path

from src.common.logger import get_logger
from src.extraction.base import ContentBlock, ExtractedContent
from src.search.searcher import MatchInfo


# ---------------------------------------------------------------------------
# 型エイリアス
# ---------------------------------------------------------------------------

#: id(ContentBlock) → [(start, end), ...] のマッピング型
_MatchMap = dict[int, list[tuple[int, int]]]

#: テキスト → ContentBlock の検索用マッピング型
_TextBlockLookup = dict[str, list[ContentBlock]]


# ---------------------------------------------------------------------------
# CSS スタイル定義（全形式共通）
# ---------------------------------------------------------------------------

_BASE_CSS = """
<style>
  /* ── 共通 ─────────────────────────────────────── */
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: 'Segoe UI', 'Yu Gothic UI', 'Meiryo', sans-serif;
    font-size: 14px;
    line-height: 1.7;
    background: #f4f4f4;
    color: #222;
  }
  .match-highlight {
    background: #ffeb3b;
    padding: 1px 2px;
    border-radius: 2px;
    font-weight: bold;
    outline: 1px solid #f0c400;
  }

  /* ── Word ───────────────────────────────────────── */
  .word-body {
    max-width: 840px;
    margin: 24px auto;
    padding: 54px 68px;
    background: #fff;
    border: 1px solid #c8c8c8;
    box-shadow: 0 3px 12px rgba(0,0,0,.15);
    min-height: 700px;
  }
  .word-body h1 { font-size: 2em;    margin: .67em 0; color: #1a1a1a; border-bottom: 1px solid #ddd; padding-bottom: .2em; }
  .word-body h2 { font-size: 1.5em;  margin: .75em 0; color: #1a1a1a; border-bottom: 1px solid #eee; padding-bottom: .15em; }
  .word-body h3 { font-size: 1.17em; margin: .83em 0; color: #1a1a1a; }
  .word-body h4 { font-size: 1.05em; margin: .89em 0; color: #333; }
  .word-body h5 { font-size: .9em;   margin: 1em 0;   color: #555; }
  .word-body h6 { font-size: .8em;   margin: 1em 0;   color: #777; }
  .word-body p  { margin: .4em 0; }
  .word-body table {
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
    table-layout: auto;
  }
  .word-body td, .word-body th {
    border: 1px solid #aaa;
    padding: 5px 10px;
    vertical-align: top;
  }
  .word-body th { background: #f0f0f0; font-weight: bold; }
  .word-list-item {
    display: flex;
    gap: 6px;
    margin: .2em 0;
  }
  .word-list-bullet { flex-shrink: 0; user-select: none; }
  .word-list-content { flex: 1; }

  /* ── Excel ──────────────────────────────────────── */
  .excel-wrapper { padding: 12px; }
  .sheet-nav {
    display: flex;
    gap: 0;
    margin-bottom: 0;
    flex-wrap: wrap;
    border-bottom: 1px solid #bbb;
  }
  .sheet-tab {
    display: inline-block;
    padding: 5px 16px;
    border: 1px solid #bbb;
    border-bottom: none;
    background: #e8e8e8;
    border-radius: 4px 4px 0 0;
    font-size: 12px;
    color: #444;
    margin-right: 2px;
    position: relative;
    top: 1px;
  }
  .sheet-tab.active {
    background: #fff;
    font-weight: bold;
    color: #1a73e8;
    border-bottom: 1px solid #fff;
    z-index: 1;
  }
  .excel-sheet-block { margin-bottom: 32px; }
  .sheet-label {
    font-size: 13px;
    font-weight: bold;
    color: #1a73e8;
    padding: 6px 8px;
    background: #e8f0fe;
    border-left: 4px solid #1a73e8;
    margin-bottom: 6px;
  }
  .excel-table {
    border-collapse: collapse;
    font-size: 13px;
    background: #fff;
    border: 2px solid #bbb;
    max-width: 100%;
  }
  .excel-table th {
    background: #f3f3f3;
    border: 1px solid #bbb;
    padding: 4px 8px;
    text-align: center;
    font-weight: bold;
    color: #555;
    min-width: 70px;
    user-select: none;
    white-space: nowrap;
  }
  .excel-table td {
    border: 1px solid #d0d0d0;
    padding: 3px 8px;
    min-width: 70px;
    max-width: 300px;
    white-space: pre-wrap;
    word-break: break-word;
    vertical-align: middle;
  }
  .excel-table td.row-header {
    background: #f3f3f3;
    text-align: center;
    font-weight: bold;
    color: #555;
    min-width: 36px;
    max-width: 36px;
    user-select: none;
    border: 1px solid #bbb;
  }

  /* ── PowerPoint ─────────────────────────────────── */
  .pptx-wrapper { padding: 16px 12px; background: #666; }
  .slide-outer {
    max-width: 900px;
    margin: 0 auto 28px auto;
    box-shadow: 0 4px 20px rgba(0,0,0,.55);
  }
  .slide-number-badge {
    text-align: right;
    font-size: 11px;
    color: #ccc;
    padding: 2px 6px 4px;
    background: #555;
    user-select: none;
  }
  .slide-canvas-wrapper {
    position: relative;
    width: 100%;
    overflow: hidden;
  }
  .slide-canvas-inner {
    position: absolute;
    top: 0; left: 0;
    width: 100%; height: 100%;
  }
  /* フォールバック用カードレイアウト */
  .slide-card {
    max-width: 860px;
    margin: 0 auto 24px auto;
    border: 1px solid #bbb;
    border-radius: 4px;
    overflow: hidden;
    box-shadow: 0 2px 8px rgba(0,0,0,.2);
    background: #fff;
  }
  .slide-header-bar {
    background: linear-gradient(135deg, #1a237e 0%, #3949ab 100%);
    padding: 10px 20px;
    color: #fff;
    font-size: 11px;
    letter-spacing: .5px;
  }
  .slide-title {
    padding: 20px 28px 8px;
    font-size: 1.5em;
    font-weight: bold;
    color: #1a237e;
    border-bottom: 2px solid #e8eaf6;
  }
  .slide-body {
    padding: 14px 28px 24px;
    font-size: 14px;
    line-height: 1.7;
  }
  .slide-body p { margin: .35em 0; }
  /* シェイプ内要素（リッチレンダリング用） */
  .pptx-shape {
    position: absolute;
    overflow: hidden;
    padding: 4px;
  }
  .pptx-shape p {
    margin: 0;
    line-height: 1.4;
  }

  /* ── PDF ────────────────────────────────────────── */
  .pdf-wrapper { padding: 16px; }
  .pdf-page {
    max-width: 840px;
    margin: 0 auto 28px auto;
    background: #fff;
    border: 1px solid #ccc;
    box-shadow: 0 2px 8px rgba(0,0,0,.12);
  }
  .pdf-page-header {
    background: #c62828;
    color: #fff;
    font-size: 12px;
    padding: 6px 16px;
    letter-spacing: .5px;
  }
  .pdf-page-body {
    padding: 32px 48px;
    font-size: 14px;
    line-height: 1.85;
    white-space: pre-wrap;
    word-break: break-word;
  }

  /* ── テキスト / ログ ────────────────────────────── */
  .text-wrapper {
    margin: 0;
    padding: 0;
    background: #1e1e1e;
    color: #d4d4d4;
    font-family: 'Cascadia Code', 'Consolas', 'Courier New', monospace;
    font-size: 13px;
    line-height: 1.6;
  }
  .text-line {
    display: flex;
    padding: 0 8px;
  }
  .text-line:hover { background: rgba(255,255,255,.05); }
  .line-no {
    user-select: none;
    min-width: 48px;
    padding-right: 12px;
    text-align: right;
    color: #858585;
    border-right: 1px solid #404040;
    margin-right: 12px;
    flex-shrink: 0;
  }
  .line-content { white-space: pre-wrap; word-break: break-all; }

  /* ── Markdown ───────────────────────────────────── */
  .md-body {
    max-width: 800px;
    margin: 24px auto;
    padding: 32px 40px;
    background: #fff;
    border: 1px solid #ddd;
    border-radius: 6px;
    box-shadow: 0 1px 4px rgba(0,0,0,.08);
  }
  .md-body h1 {
    font-size: 2em; margin: .6em 0 .3em;
    border-bottom: 2px solid #eee; padding-bottom: .2em;
  }
  .md-body h2 {
    font-size: 1.5em; margin: .6em 0 .3em;
    border-bottom: 1px solid #eee; padding-bottom: .15em;
  }
  .md-body h3 { font-size: 1.2em; margin: .6em 0 .2em; }
  .md-body h4, .md-body h5, .md-body h6 { margin: .5em 0 .2em; }
  .md-body p  { margin: .5em 0; }
  .md-body code {
    background: #f4f4f4;
    padding: 1px 5px;
    border-radius: 3px;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: .9em;
  }
  .md-body pre {
    background: #1e1e1e;
    color: #d4d4d4;
    padding: 16px;
    border-radius: 6px;
    overflow-x: auto;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 13px;
  }
  .md-body ul, .md-body ol { margin: .4em 0; padding-left: 1.8em; }
  .md-body blockquote {
    border-left: 4px solid #ddd;
    padding-left: 1em;
    color: #666;
    margin: .5em 0;
  }
  .md-body table { border-collapse: collapse; width: 100%; margin: .8em 0; }
  .md-body td, .md-body th { border: 1px solid #ccc; padding: 6px 12px; }
  .md-body th { background: #f5f5f5; }
  .md-body hr { border: none; border-top: 1px solid #ddd; margin: 1em 0; }

  /* ── 文字コードバッジ ────────────────────────────── */
  .encoding-badge {
    position: fixed;
    bottom: 10px;
    right: 12px;
    background: rgba(0,0,0,.55);
    color: #fff;
    font-size: 11px;
    padding: 3px 8px;
    border-radius: 4px;
  }
</style>
"""


class PreviewRenderer:
    """プレビューレンダラー。

    :class:`ExtractedContent` を受け取り、ファイル形式に応じた HTML を生成する。
    Office 系ファイルはリッチレンダリング（書式情報を再抽出）を試みる。
    マッチ箇所は ``.match-highlight`` クラスでハイライトし、JS スクロールと連動する。
    """

    def __init__(self) -> None:
        self._logger = get_logger("preview")

    # ------------------------------------------------------------------
    # 公開 API
    # ------------------------------------------------------------------

    def render_full(
        self,
        content: ExtractedContent,
        matches: list[MatchInfo] | None = None,
        page_filter: int | None = None,
        sheet_filter: str | None = None,
        slide_filter: int | None = None,
    ) -> str:
        """ファイル全体（または指定ページ / シート / スライド）を HTML にレンダリングする。"""
        # レンダーキャッシュを確認
        from src.extraction.cache import get_render_cache
        import hashlib as _hashlib

        match_sig = str(
            [(m.start, m.end, m.text[:20]) for m in (matches or [])]
        )
        match_hash = _hashlib.md5(match_sig.encode()).hexdigest()[:8]
        try:
            mtime = content.file_path.stat().st_mtime_ns
        except OSError:
            mtime = 0
        cache_key = (
            f"{content.file_path}:{mtime}:{page_filter}:{sheet_filter}"
            f":{slide_filter}:{match_hash}"
        )
        render_cache = get_render_cache()
        cached = render_cache.get(cache_key)
        if cached is not None:
            return cached

        match_map = _build_match_map(matches) if matches else {}
        ext = content.file_path.suffix.lower().lstrip(".")

        if ext == "docx":
            body = self._render_word(content, match_map)
        elif ext == "xlsx":
            body = self._render_excel(content, match_map, sheet_filter)
        elif ext == "pptx":
            body = self._render_pptx(content, match_map, slide_filter)
        elif ext == "pdf":
            body = self._render_pdf(content, match_map, page_filter)
        elif ext == "md":
            body = self._render_markdown(content, match_map)
        else:
            body = self._render_plain_text(content, match_map)

        result_html = _wrap_html(body, content.encoding)
        render_cache.put(cache_key, result_html)
        return result_html

    def render_match(
        self,
        match: MatchInfo,
        content: ExtractedContent,
    ) -> str:
        """マッチ箇所を中心にしたミニプレビューを HTML にレンダリングする。"""
        match_map = _build_match_map([match])
        highlighted = _highlight_block(match.block, match_map)
        ext = content.file_path.suffix.lower().lstrip(".")

        location = html.escape(match.get_location_info())
        header_class = _location_header_class(ext)
        body = (
            f'<div class="{header_class}">{location}</div>'
            f'<div style="padding:8px 16px;">{highlighted}</div>'
        )
        return _wrap_html(body, content.encoding)

    # ------------------------------------------------------------------
    # Word レンダラー
    # ------------------------------------------------------------------

    def _render_word(
        self,
        content: ExtractedContent,
        match_map: _MatchMap,
    ) -> str:
        """Word をリッチレンダリング（失敗時はテキストのみの簡易版にフォールバック）。"""
        try:
            return self._render_word_rich(content, match_map)
        except Exception as exc:
            self._logger.warning(
                "render",
                f"Rich Word rendering failed, falling back: {exc}",
                file_path=str(content.file_path),
            )
            return self._render_word_fallback(content, match_map)

    def _render_word_rich(
        self,
        content: ExtractedContent,
        match_map: _MatchMap,
    ) -> str:
        """Word (.docx) を書式情報付きでリッチレンダリングする。

        - ``doc.element.body`` を走査して段落と表を文書順に描画する
        - run 単位で bold / italic / underline / color / font-size を適用する
        - リスト段落はインデント付きの箇条書き / 番号付きリストとして描画する
        """
        from docx import Document
        from docx.oxml.ns import qn
        from docx.text.paragraph import Paragraph
        from docx.table import Table as DocxTable

        doc = Document(content.file_path)
        block_lookup = _build_text_block_lookup(content.blocks)

        parts = ['<div class="word-body">']

        for child in doc.element.body:
            tag = child.tag
            if tag == qn("w:p"):
                para = Paragraph(child, doc)
                rendered = _render_word_paragraph(para, block_lookup, match_map)
                if rendered:
                    parts.append(rendered)
            elif tag == qn("w:tbl"):
                table = DocxTable(child, doc)
                parts.append(_render_word_table(table, block_lookup, match_map))
            # w:sectPr（セクションプロパティ）はスキップ

        parts.append("</div>")
        return "\n".join(parts)

    def _render_word_fallback(
        self,
        content: ExtractedContent,
        match_map: _MatchMap,
    ) -> str:
        """Word のテキストのみの簡易レンダリング（フォールバック）。"""
        parts = ['<div class="word-body">']
        for block in content.blocks:
            highlighted = _highlight_block(block, match_map)
            if block.heading_level and 1 <= block.heading_level <= 6:
                tag = f"h{block.heading_level}"
                parts.append(f"<{tag}>{highlighted}</{tag}>")
            elif block.list_level is not None:
                indent_px = 24 + block.list_level * 20
                bullet = "1." if block.list_is_ordered else "•"
                parts.append(
                    f'<div class="word-list-item" style="margin-left:{indent_px}px">'
                    f'<span class="word-list-bullet">{bullet}</span>'
                    f'<span class="word-list-content">{highlighted}</span>'
                    f"</div>"
                )
            else:
                parts.append(f"<p>{highlighted}</p>")
        parts.append("</div>")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Excel レンダラー
    # ------------------------------------------------------------------

    def _render_excel(
        self,
        content: ExtractedContent,
        match_map: _MatchMap,
        sheet_filter: str | None,
    ) -> str:
        """Excel をリッチレンダリング（失敗時は簡易版にフォールバック）。"""
        try:
            # 30 MB 超のファイルはフォールバック（openpyxl の read_only なしは重い）
            file_size = content.file_path.stat().st_size
            if file_size > 30 * 1024 * 1024:
                raise ValueError("file too large for rich rendering")
            return self._render_excel_rich(content, match_map, sheet_filter)
        except Exception as exc:
            self._logger.warning(
                "render",
                f"Rich Excel rendering failed, falling back: {exc}",
                file_path=str(content.file_path),
            )
            return self._render_excel_fallback(content, match_map, sheet_filter)

    def _render_excel_rich(
        self,
        content: ExtractedContent,
        match_map: _MatchMap,
        sheet_filter: str | None,
    ) -> str:
        """Excel (.xlsx) を書式情報（色・太字・配置・マージセル）付きでレンダリングする。"""
        from openpyxl import load_workbook

        # read_only=False でセル書式を取得する
        wb = load_workbook(content.file_path, data_only=True)
        block_lookup = _build_text_block_lookup(content.blocks)

        sheet_names = (
            [sheet_filter]
            if sheet_filter and sheet_filter in wb.sheetnames
            else wb.sheetnames
        )

        parts = ['<div class="excel-wrapper">']

        if len(sheet_names) > 1:
            parts.append('<div class="sheet-nav">')
            for sname in sheet_names:
                is_active = (sheet_filter is None and sname == sheet_names[0]) or sname == sheet_filter
                active_cls = "active" if is_active else ""
                parts.append(
                    f'<span class="sheet-tab {active_cls}">'
                    f"{html.escape(sname)}</span>"
                )
            parts.append("</div>")

        for sheet_name in sheet_names:
            ws = wb[sheet_name]
            parts.append('<div class="excel-sheet-block">')
            if len(sheet_names) > 1:
                parts.append(
                    f'<div class="sheet-label">📋 {html.escape(sheet_name)}</div>'
                )
            parts.append(
                _render_excel_grid_rich(ws, block_lookup, match_map)
            )
            parts.append("</div>")

        wb.close()
        parts.append("</div>")
        return "\n".join(parts)

    def _render_excel_fallback(
        self,
        content: ExtractedContent,
        match_map: _MatchMap,
        sheet_filter: str | None,
    ) -> str:
        """Excel のテキストのみの簡易レンダリング（フォールバック）。"""
        sheets: dict[str, list[ContentBlock]] = {}
        for block in content.blocks:
            sheets.setdefault(block.sheet or "", []).append(block)

        if sheet_filter is not None:
            sheets = {k: v for k, v in sheets.items() if k == sheet_filter}

        parts = ['<div class="excel-wrapper">']

        if len(sheets) > 1:
            parts.append('<div class="sheet-nav">')
            for sname in sheets:
                active = "active" if sheet_filter is None or sname == sheet_filter else ""
                parts.append(
                    f'<span class="sheet-tab {active}">'
                    f"{html.escape(sname)}</span>"
                )
            parts.append("</div>")

        for sheet_name, blocks in sheets.items():
            parts.append(
                f'<div class="excel-sheet-block">'
                f'<div class="sheet-label">📋 {html.escape(sheet_name)}</div>'
            )
            parts.append(_render_excel_grid(blocks, match_map))
            parts.append("</div>")

        parts.append("</div>")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # PowerPoint レンダラー
    # ------------------------------------------------------------------

    def _render_pptx(
        self,
        content: ExtractedContent,
        match_map: _MatchMap,
        slide_filter: int | None,
    ) -> str:
        """PowerPoint をリッチレンダリング（失敗時は簡易版にフォールバック）。"""
        try:
            return self._render_pptx_rich(content, match_map, slide_filter)
        except Exception as exc:
            self._logger.warning(
                "render",
                f"Rich PowerPoint rendering failed, falling back: {exc}",
                file_path=str(content.file_path),
            )
            return self._render_pptx_fallback(content, match_map, slide_filter)

    def _render_pptx_rich(
        self,
        content: ExtractedContent,
        match_map: _MatchMap,
        slide_filter: int | None,
    ) -> str:
        """PowerPoint (.pptx) をアスペクト比を保持したスライドレイアウトでレンダリングする。

        - プレゼンテーションのスライドサイズからアスペクト比を計算する
        - シェイプの left / top / width / height をスライドサイズに対する % で配置する
        - スライド背景色（ソリッドフィル）を適用する
        - run 単位でフォントサイズ・色・bold / italic を反映する
        - 箇条書きレベルに応じてインデントを付与する
        """
        from pptx import Presentation
        from pptx.util import Emu

        prs = Presentation(content.file_path)
        slide_width: int = prs.slide_width
        slide_height: int = prs.slide_height
        aspect_ratio = slide_height / slide_width  # padding-top % のベース

        block_lookup = _build_text_block_lookup(content.blocks)

        slide_nums_to_render: set[int] = set()
        if slide_filter is not None:
            slide_nums_to_render.add(slide_filter)
        else:
            slide_nums_to_render = set(range(1, len(prs.slides) + 1))

        parts = ['<div class="pptx-wrapper">']

        for slide_num, slide in enumerate(prs.slides, start=1):
            if slide_num not in slide_nums_to_render:
                continue

            bg_css = _pptx_background_css(slide)

            parts.append('<div class="slide-outer">')
            parts.append(
                f'<div class="slide-number-badge">スライド {slide_num} / '
                f'{len(prs.slides)}</div>'
            )
            parts.append(
                f'<div class="slide-canvas-wrapper" '
                f'style="padding-top:{aspect_ratio * 100:.4f}%;">'
            )
            parts.append(
                f'<div class="slide-canvas-inner" style="{bg_css}">'
            )

            for shape in slide.shapes:
                shape_html = _render_pptx_shape(
                    shape, slide_width, slide_height, block_lookup, match_map
                )
                if shape_html:
                    parts.append(shape_html)

            parts.append("</div>")  # slide-canvas-inner
            parts.append("</div>")  # slide-canvas-wrapper
            parts.append("</div>")  # slide-outer

        parts.append("</div>")
        return "\n".join(parts)

    def _render_pptx_fallback(
        self,
        content: ExtractedContent,
        match_map: _MatchMap,
        slide_filter: int | None,
    ) -> str:
        """PowerPoint のシンプルなカードレイアウト（フォールバック）。"""
        slides: dict[int, list[ContentBlock]] = {}
        for block in content.blocks:
            slides.setdefault(block.slide or 0, []).append(block)

        if slide_filter is not None:
            slides = {k: v for k, v in slides.items() if k == slide_filter}

        parts = ['<div class="pptx-wrapper" style="background:#f4f4f4;padding:16px;">']
        for slide_num, blocks in sorted(slides.items()):
            title_blocks = [b for b in blocks if b.is_slide_title]
            body_blocks = [b for b in blocks if not b.is_slide_title]

            parts.append('<div class="slide-card">')
            parts.append(
                f'<div class="slide-header-bar">スライド {slide_num}</div>'
            )

            if title_blocks:
                for tb in title_blocks:
                    parts.append(
                        f'<div class="slide-title">'
                        f"{_highlight_block(tb, match_map)}</div>"
                    )
            else:
                parts.append(
                    '<div class="slide-title" style="color:#aaa;">（タイトルなし）</div>'
                )

            parts.append('<div class="slide-body">')
            for bb in body_blocks:
                parts.append(f"<p>{_highlight_block(bb, match_map)}</p>")
            parts.append("</div>")
            parts.append("</div>")

        parts.append("</div>")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # PDF レンダラー
    # ------------------------------------------------------------------

    def _render_pdf(
        self,
        content: ExtractedContent,
        match_map: _MatchMap,
        page_filter: int | None,
    ) -> str:
        """PDF をページフレーム付きでレンダリングする。"""
        pages: dict[int, list[ContentBlock]] = {}
        for block in content.blocks:
            pages.setdefault(block.page or 0, []).append(block)

        if page_filter is not None:
            pages = {k: v for k, v in pages.items() if k == page_filter}

        parts = ['<div class="pdf-wrapper">']
        for page_num, blocks in sorted(pages.items()):
            parts.append('<div class="pdf-page">')
            parts.append(
                f'<div class="pdf-page-header">📄 ページ {page_num}</div>'
            )
            parts.append('<div class="pdf-page-body">')
            for block in blocks:
                parts.append(_highlight_block(block, match_map))
                parts.append("\n")
            parts.append("</div></div>")

        parts.append("</div>")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Markdown レンダラー
    # ------------------------------------------------------------------

    def _render_markdown(
        self,
        content: ExtractedContent,
        match_map: _MatchMap,
    ) -> str:
        """Markdown (.md) を GitHub 風にレンダリングする。"""
        parts = ['<div class="md-body">']
        in_code_block = False
        code_lines: list[str] = []

        for block in content.blocks:
            raw = block.text
            highlighted = _highlight_block(block, match_map)

            if raw.startswith("```"):
                if not in_code_block:
                    in_code_block = True
                    code_lines = []
                else:
                    in_code_block = False
                    code_html = html.escape("\n".join(code_lines))
                    parts.append(f"<pre><code>{code_html}</code></pre>")
                continue

            if in_code_block:
                code_lines.append(raw)
                continue

            heading_match = re.match(r"^(#{1,6})\s+(.*)", raw)
            if heading_match:
                level = len(heading_match.group(1))
                text_part = heading_match.group(2)
                inner = _apply_inline_md(
                    _highlight_segment(text_part, raw, block, match_map)
                )
                parts.append(f"<h{level}>{inner}</h{level}>")
                continue

            if re.match(r"^[-*_]{3,}$", raw.strip()):
                parts.append("<hr>")
                continue

            if raw.startswith(">"):
                trimmed = (
                    highlighted[len("&gt;"):].lstrip()
                    if highlighted.startswith("&gt;")
                    else highlighted[1:].lstrip()
                )
                parts.append(
                    f"<blockquote><p>{_apply_inline_md(trimmed)}</p></blockquote>"
                )
                continue

            list_match = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)", raw)
            if list_match:
                indent = len(list_match.group(1))
                marker = list_match.group(2)
                text_part = list_match.group(3)
                inner = _apply_inline_md(text_part)
                tag = "ol" if re.match(r"\d+\.", marker) else "ul"
                style = f"margin-left:{indent * 12}px" if indent else ""
                parts.append(f"<{tag} style='{style}'><li>{inner}</li></{tag}>")
                continue

            inner = _apply_inline_md(highlighted)
            if inner.strip():
                parts.append(f"<p>{inner}</p>")

        parts.append("</div>")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # テキスト / ログ レンダラー
    # ------------------------------------------------------------------

    def _render_plain_text(
        self,
        content: ExtractedContent,
        match_map: _MatchMap,
    ) -> str:
        """テキスト / ログをエディター風（行番号付き）にレンダリングする。"""
        parts = [
            '<div class="text-wrapper">'
            '<table style="border-spacing:0;width:100%;padding:8px 0;">'
        ]
        for block in content.blocks:
            line_no_html = (
                f'<td class="line-no">{block.line}</td>'
                if block.line is not None
                else ""
            )
            highlighted = _highlight_block(block, match_map)
            parts.append(
                f'<tr class="text-line">'
                f"{line_no_html}"
                f'<td class="line-content">{highlighted}</td>'
                f"</tr>"
            )
        parts.append("</table></div>")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Word リッチレンダリング ヘルパー
# ---------------------------------------------------------------------------

def _render_word_paragraph(
    para: object,
    block_lookup: "_TextBlockLookup",
    match_map: _MatchMap,
) -> str:
    """Word 段落を HTML 要素にレンダリングする。

    空段落は ``<p>&nbsp;</p>`` として返す（行間を保持するため）。
    見出し / リスト / 通常段落を判別し、run 単位の書式も適用する。
    """
    style_name: str = ""
    try:
        style_name = para.style.name or ""  # type: ignore[union-attr]
    except Exception:
        pass

    full_text: str = para.text  # type: ignore[union-attr]
    stripped = full_text.strip()

    # 空段落をスペーサーとして描画
    if not stripped:
        return '<p style="margin:.15em 0;">&nbsp;</p>'

    heading_level = _parse_heading_level_local(style_name)
    list_level, list_is_ordered = _parse_list_info_local(style_name)

    # マッチブロックをテキストで検索
    block = _find_block_by_text(stripped, block_lookup)

    # 配置スタイル
    align_css = _get_para_align_css(para)
    # インデントスタイル（リストは別途処理）
    indent_css = _get_para_indent_css(para) if list_level is None else ""

    # run 単位でのレンダリング（ハイライト + 書式）
    inner_html = _render_word_runs_with_highlight(para, block, match_map)

    if heading_level and 1 <= heading_level <= 6:
        style = f"{align_css}{indent_css}"
        return f'<h{heading_level} style="{style}">{inner_html}</h{heading_level}>'

    if list_level is not None:
        base_indent = 24 + list_level * 20
        bullet_char = "○" if list_is_ordered else "•"
        if list_level == 0:
            bullet_char = "1." if list_is_ordered else "•"
        return (
            f'<div class="word-list-item" style="margin-left:{base_indent}px;">'
            f'<span class="word-list-bullet">{bullet_char}</span>'
            f'<span class="word-list-content" style="{align_css}">{inner_html}</span>'
            f"</div>"
        )

    style = f"{align_css}{indent_css}"
    return f'<p style="{style}">{inner_html}</p>'


def _render_word_table(
    table: object,
    block_lookup: "_TextBlockLookup",
    match_map: _MatchMap,
) -> str:
    """Word 表を HTML テーブルとしてレンダリングする。

    結合セルの重複描画を避けるため走査済み座標を追跡する。
    """
    parts = ['<table class="word-table" style="border-collapse:collapse;width:100%;margin:1em 0;">']
    seen: set[tuple[int, int]] = set()

    try:
        rows = table.rows  # type: ignore[union-attr]
    except Exception:
        return ""

    for ri, row in enumerate(rows):
        parts.append("<tr>")
        try:
            cells = row.cells
        except Exception:
            cells = []
        for ci, cell in enumerate(cells):
            if (ri, ci) in seen:
                continue
            seen.add((ri, ci))
            text = cell.text.strip()
            block = _find_block_by_text(text, block_lookup)
            highlighted = (
                _highlight_block(block, match_map)
                if block
                else html.escape(text)
            )
            is_header = ri == 0
            tag = "th" if is_header else "td"
            bg_style = "background:#f5f5f5;" if is_header else ""
            parts.append(
                f'<{tag} style="border:1px solid #aaa;padding:5px 10px;'
                f'vertical-align:top;{bg_style}">{highlighted}</{tag}>'
            )
        parts.append("</tr>")

    parts.append("</table>")
    return "\n".join(parts)


def _render_word_runs_with_highlight(
    para: object,
    block: ContentBlock | None,
    match_map: _MatchMap,
) -> str:
    """段落の run リストを走査し、書式 + ハイライトを適用した HTML を返す。

    アルゴリズム:
    1. 全 run のテキストと文書内オフセットを収集する
    2. ハイライト境界と run 境界をマージしてイベント列を構築する
    3. 各区間に対して (run書式, ハイライト) を組み合わせた span を出力する
    """
    positions: list[tuple[int, int]] = []
    if block is not None:
        positions = match_map.get(id(block), [])

    try:
        runs = para.runs  # type: ignore[union-attr]
    except Exception:
        # run が取得できない場合は単純なハイライト
        full_text = getattr(para, "text", "")
        return _highlight_segments(full_text, positions)

    # run ごとの (開始位置, 終了位置, run オブジェクト) を構築
    run_spans: list[tuple[int, int, object]] = []
    cursor = 0
    for run in runs:
        t = run.text
        run_spans.append((cursor, cursor + len(t), run))
        cursor += len(t)
    full_text = "".join(r.text for r in runs)

    if not run_spans or not full_text:
        return html.escape(full_text)

    # イベント列（境界点の集合）を構築
    events: set[int] = {0, len(full_text)}
    for s, e, _ in run_spans:
        events.add(s)
        events.add(e)
    for s, e in positions:
        events.add(max(0, s))
        events.add(min(len(full_text), e))
    sorted_events = sorted(events)

    parts: list[str] = []

    for i in range(len(sorted_events) - 1):
        seg_start = sorted_events[i]
        seg_end = sorted_events[i + 1]
        if seg_start >= seg_end:
            continue

        seg_text = full_text[seg_start:seg_end]
        if not seg_text:
            continue

        # この区間を含む run を探す
        run_obj = None
        for rs, re, r in run_spans:
            if rs <= seg_start < re:
                run_obj = r
                break

        # ハイライト判定（区間が少しでも重なれば適用）
        is_highlighted = any(
            hs < seg_end and he > seg_start for hs, he in positions
        )

        # run 書式を CSS に変換
        run_styles: list[str] = []
        if run_obj is not None:
            run_styles = _get_run_style_list(run_obj)

        escaped = html.escape(seg_text)

        if is_highlighted:
            hl_style = (
                "background:#ffeb3b;font-weight:bold;"
                "outline:1px solid #f0c400;padding:1px 2px;border-radius:2px;"
            )
            combined = ";".join(run_styles) + (";" if run_styles else "") + hl_style
            parts.append(
                f'<span class="match-highlight" style="{combined}">{escaped}</span>'
            )
        elif run_styles:
            parts.append(f'<span style="{";".join(run_styles)}">{escaped}</span>')
        else:
            parts.append(escaped)

    return "".join(parts)


def _get_run_style_list(run: object) -> list[str]:
    """python-docx の Run オブジェクトから CSS スタイル文字列のリストを返す。"""
    styles: list[str] = []
    try:
        if run.bold:  # type: ignore[union-attr]
            styles.append("font-weight:bold")
    except Exception:
        pass
    try:
        if run.italic:  # type: ignore[union-attr]
            styles.append("font-style:italic")
    except Exception:
        pass
    try:
        if run.underline:  # type: ignore[union-attr]
            styles.append("text-decoration:underline")
    except Exception:
        pass
    try:
        size = run.font.size  # type: ignore[union-attr]
        if size is not None:
            pt = size.pt
            if 4 <= pt <= 96:
                styles.append(f"font-size:{pt:.0f}pt")
    except Exception:
        pass
    try:
        color = run.font.color  # type: ignore[union-attr]
        if color is not None and color.type is not None:
            rgb_val = str(color.rgb)
            if rgb_val and rgb_val not in ("None", "000000", "auto"):
                # 上位 2 桁はアルファチャンネルの場合があるので最後 6 文字を使う
                hex_color = rgb_val[-6:]
                if re.match(r"^[0-9A-Fa-f]{6}$", hex_color):
                    styles.append(f"color:#{hex_color}")
    except Exception:
        pass
    return styles


def _get_para_align_css(para: object) -> str:
    """段落の配置を CSS text-align 文字列で返す。取得失敗時は空文字列。"""
    try:
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        align = para.alignment  # type: ignore[union-attr]
        mapping = {
            WD_ALIGN_PARAGRAPH.CENTER: "text-align:center;",
            WD_ALIGN_PARAGRAPH.RIGHT: "text-align:right;",
            WD_ALIGN_PARAGRAPH.JUSTIFY: "text-align:justify;",
        }
        return mapping.get(align, "")
    except Exception:
        return ""


def _get_para_indent_css(para: object) -> str:
    """段落の左インデントを CSS margin-left 文字列で返す。"""
    try:
        indent = para.paragraph_format.left_indent  # type: ignore[union-attr]
        if indent is not None:
            px = int(indent.pt * 1.333)
            if px > 0:
                return f"margin-left:{px}px;"
    except Exception:
        pass
    return ""


def _parse_heading_level_local(style_name: str) -> int | None:
    """Word スタイル名から見出しレベルを返す（ローカル版、importなし）。"""
    if not style_name:
        return None
    parts = style_name.split()
    if len(parts) >= 2 and parts[0].lower() in ("heading", "見出し"):
        try:
            level = int(parts[-1])
            return level if 1 <= level <= 6 else None
        except ValueError:
            return None
    return None


def _parse_list_info_local(style_name: str) -> tuple[int | None, bool]:
    """Word スタイル名からリスト情報を返す（ローカル版、importなし）。"""
    if not style_name:
        return (None, False)
    name_lower = style_name.lower()
    bullet_prefixes = ("list bullet", "list paragraph", "bullet list",
                       "箇条書き", "リスト段落")
    number_prefixes = ("list number", "list continue", "番号付き", "リスト番号")
    for prefix in bullet_prefixes:
        if name_lower.startswith(prefix):
            suffix = name_lower[len(prefix):].strip()
            try:
                level = max(0, int(suffix) - 1)
            except ValueError:
                level = 0
            return (level, False)
    for prefix in number_prefixes:
        if name_lower.startswith(prefix):
            suffix = name_lower[len(prefix):].strip()
            try:
                level = max(0, int(suffix) - 1)
            except ValueError:
                level = 0
            return (level, True)
    return (None, False)


# ---------------------------------------------------------------------------
# Excel リッチレンダリング ヘルパー
# ---------------------------------------------------------------------------

def _render_excel_grid_rich(
    ws: object,
    block_lookup: "_TextBlockLookup",
    match_map: _MatchMap,
) -> str:
    """openpyxl ワークシートオブジェクトからリッチなグリッド HTML を生成する。

    - セルの塗りつぶし色・フォント色・太字・配置を CSS で表現する
    - マージセルを colspan / rowspan で表現する
    - 数値フォーマット（日付・パーセント・通貨）を適用する
    """
    from openpyxl.utils import get_column_letter

    # ─ マージセル情報を収集 ─
    # {(row, col): (rowspan, colspan)} の辞書（左上セルのみ）
    merge_info: dict[tuple[int, int], tuple[int, int]] = {}
    # スキップすべき（マージ先）セル座標の集合
    merged_skip: set[tuple[int, int]] = set()

    try:
        for cell_range in ws.merged_cells.ranges:
            top_left = (cell_range.min_row, cell_range.min_col)
            rs = cell_range.max_row - cell_range.min_row + 1
            cs = cell_range.max_col - cell_range.min_col + 1
            merge_info[top_left] = (rs, cs)
            for r in range(cell_range.min_row, cell_range.max_row + 1):
                for c in range(cell_range.min_col, cell_range.max_col + 1):
                    if (r, c) != top_left:
                        merged_skip.add((r, c))
    except Exception:
        pass  # マージセル情報が取得できない場合は無視

    # ─ 使用範囲を確認 ─
    min_row = ws.min_row or 1  # type: ignore[union-attr]
    max_row = ws.max_row or 1  # type: ignore[union-attr]
    min_col = ws.min_column or 1  # type: ignore[union-attr]
    max_col = ws.max_column or 1  # type: ignore[union-attr]

    if max_row < min_row or max_col < min_col:
        return '<p style="color:#aaa;padding:8px;">（データなし）</p>'

    parts = ['<div style="overflow-x:auto;"><table class="excel-table">']

    # ─ 列ヘッダー行 ─
    parts.append("<tr><th></th>")
    for c in range(min_col, max_col + 1):
        parts.append(f"<th>{get_column_letter(c)}</th>")
    parts.append("</tr>")

    # ─ データ行 ─
    for r in range(min_row, max_row + 1):
        parts.append(f'<tr><td class="row-header">{r}</td>')
        for c in range(min_col, max_col + 1):
            if (r, c) in merged_skip:
                continue  # マージ先はスキップ

            cell = ws.cell(row=r, column=c)  # type: ignore[union-attr]
            value = cell.value
            text_val = _excel_format_value(cell)

            # マッチブロックを探す（テキスト値でルックアップ）
            block = _find_block_by_text(str(value).strip() if value is not None else "", block_lookup)

            if block is not None:
                cell_html = _highlight_block(block, match_map)
            else:
                cell_html = html.escape(text_val)

            # span / colspan / rowspan
            span_attrs = ""
            if (r, c) in merge_info:
                rs, cs = merge_info[(r, c)]
                if rs > 1:
                    span_attrs += f' rowspan="{rs}"'
                if cs > 1:
                    span_attrs += f' colspan="{cs}"'

            # 書式 CSS
            cell_style = _excel_cell_css(cell)

            parts.append(
                f'<td style="{cell_style}"{span_attrs}>{cell_html}</td>'
            )
        parts.append("</tr>")

    parts.append("</table></div>")
    return "\n".join(parts)


def _excel_cell_css(cell: object) -> str:
    """openpyxl セルオブジェクトから CSS スタイル文字列を生成する。"""
    styles: list[str] = []

    # 背景色（ソリッドフィルのみ）
    try:
        fill = cell.fill  # type: ignore[union-attr]
        if fill and fill.fill_type == "solid":
            fg = fill.fgColor
            if fg and fg.type == "rgb":
                color_str = str(fg.rgb)[-6:]
                if re.match(r"^[0-9A-Fa-f]{6}$", color_str) and color_str.upper() != "FFFFFF":
                    styles.append(f"background:#{color_str}")
    except Exception:
        pass

    # フォント色・太字・斜体
    try:
        font = cell.font  # type: ignore[union-attr]
        if font:
            if font.bold:
                styles.append("font-weight:bold")
            if font.italic:
                styles.append("font-style:italic")
            if font.color and font.color.type == "rgb":
                color_str = str(font.color.rgb)[-6:]
                if re.match(r"^[0-9A-Fa-f]{6}$", color_str) and color_str.upper() != "000000":
                    styles.append(f"color:#{color_str}")
            if font.size and 6 <= font.size <= 72:
                styles.append(f"font-size:{font.size:.0f}pt")
    except Exception:
        pass

    # 水平配置
    try:
        alignment = cell.alignment  # type: ignore[union-attr]
        if alignment and alignment.horizontal:
            h_map = {
                "center": "text-align:center",
                "right": "text-align:right",
                "left": "text-align:left",
            }
            css = h_map.get(alignment.horizontal)
            if css:
                styles.append(css)
    except Exception:
        pass

    return ";".join(styles)


def _excel_format_value(cell: object) -> str:
    """セルの値を number_format に従ってフォーマットした文字列で返す。"""
    value = getattr(cell, "value", None)
    if value is None:
        return ""

    number_format: str = ""
    try:
        number_format = cell.number_format or ""  # type: ignore[union-attr]
    except Exception:
        pass

    import datetime

    # 日付・時刻型の値
    if isinstance(value, (datetime.date, datetime.datetime)):
        try:
            return value.strftime("%Y/%m/%d")
        except Exception:
            return str(value)

    # 数値型のフォーマット解釈
    if isinstance(value, (int, float)):
        fmt_lower = number_format.lower()
        if "%" in fmt_lower:
            try:
                return f"{value * 100:.1f}%"
            except Exception:
                pass
        if any(c in fmt_lower for c in ("¥", "$", "€", "£")):
            currency_symbol = next(
                (c for c in ("¥", "$", "€", "£") if c in number_format), ""
            )
            try:
                return f"{currency_symbol}{value:,.0f}"
            except Exception:
                pass
        # 小数点フォーマット
        if "." in fmt_lower and "0" in fmt_lower:
            decimal_places = len(fmt_lower.split(".")[-1].rstrip(";@_* "))
            try:
                return f"{value:.{decimal_places}f}"
            except Exception:
                pass

    return str(value).strip()


# ---------------------------------------------------------------------------
# PowerPoint リッチレンダリング ヘルパー
# ---------------------------------------------------------------------------

def _pptx_background_css(slide: object) -> str:
    """スライドの背景色を CSS background 文字列で返す。取得失敗時は白を返す。"""
    try:
        fill = slide.background.fill  # type: ignore[union-attr]
        if fill.type is not None:
            rgb = fill.fore_color.rgb
            hex_color = str(rgb)[-6:]
            if re.match(r"^[0-9A-Fa-f]{6}$", hex_color):
                return f"background:#{hex_color};"
    except Exception:
        pass
    return "background:#ffffff;"


def _render_pptx_shape(
    shape: object,
    slide_width: int,
    slide_height: int,
    block_lookup: "_TextBlockLookup",
    match_map: _MatchMap,
) -> str:
    """1 つの PowerPoint シェイプを絶対配置 div として HTML にレンダリングする。

    - シェイプの left / top / width / height をスライドサイズに対する % で表現する
    - テキストフレームを持つシェイプは段落・run 単位の書式を適用する
    - 画像シェイプはプレースホルダーのみ表示する
    - テーブルシェイプは HTML テーブルとして表示する
    """
    try:
        left = getattr(shape, "left", None)
        top = getattr(shape, "top", None)
        width = getattr(shape, "width", None)
        height = getattr(shape, "height", None)

        if any(v is None for v in (left, top, width, height)):
            return ""

        # スライドサイズに対する % で表現
        l_pct = left / slide_width * 100
        t_pct = top / slide_height * 100
        w_pct = width / slide_width * 100
        h_pct = height / slide_height * 100

        pos_style = (
            f"left:{l_pct:.3f}%;top:{t_pct:.3f}%;"
            f"width:{w_pct:.3f}%;height:{h_pct:.3f}%;"
        )

    except Exception:
        return ""

    # ─ テーブルシェイプ ─
    try:
        if shape.has_table:  # type: ignore[union-attr]
            table_html = _render_pptx_table(
                shape.table, block_lookup, match_map  # type: ignore[union-attr]
            )
            return (
                f'<div class="pptx-shape" style="{pos_style}overflow:auto;">'
                f"{table_html}</div>"
            )
    except Exception:
        pass

    # ─ テキストフレームシェイプ ─
    try:
        if not hasattr(shape, "text_frame"):
            return ""
        tf = shape.text_frame  # type: ignore[union-attr]
    except Exception:
        return ""

    # テキストフレーム内の段落を HTML に変換
    para_parts: list[str] = []
    try:
        for para in tf.paragraphs:
            para_html = _render_pptx_paragraph(para, block_lookup, match_map)
            if para_html is not None:
                para_parts.append(para_html)
    except Exception:
        # テキストフレーム解析失敗時はテキストのみ
        plain_text = getattr(shape, "text", "").strip()
        if plain_text:
            block = _find_block_by_text(plain_text, block_lookup)
            cell_html = (
                _highlight_block(block, match_map) if block else html.escape(plain_text)
            )
            para_parts.append(f"<p>{cell_html}</p>")

    if not para_parts:
        return ""

    # テキストフレームの垂直配置
    v_align = "vertical-align:top;"

    content = "\n".join(para_parts)
    return (
        f'<div class="pptx-shape" style="{pos_style}{v_align}">'
        f"{content}</div>"
    )


def _render_pptx_paragraph(
    para: object,
    block_lookup: "_TextBlockLookup",
    match_map: _MatchMap,
) -> str | None:
    """PowerPoint 段落を HTML <p> 要素にレンダリングする。"""
    try:
        full_text = para.text.strip()  # type: ignore[union-attr]
    except Exception:
        return None

    if not full_text:
        return None

    block = _find_block_by_text(full_text, block_lookup)

    # 配置
    align_css = ""
    try:
        from pptx.enum.text import PP_ALIGN
        align = para.alignment  # type: ignore[union-attr]
        align_map = {
            PP_ALIGN.CENTER: "text-align:center;",
            PP_ALIGN.RIGHT: "text-align:right;",
            PP_ALIGN.JUSTIFY: "text-align:justify;",
        }
        align_css = align_map.get(align, "")
    except Exception:
        pass

    # 箇条書きインデントレベル
    bullet_indent = ""
    try:
        level = para.level or 0  # type: ignore[union-attr]
        if level > 0:
            bullet_indent = f"margin-left:{level * 20}px;"
    except Exception:
        pass

    # run 単位でのレンダリング
    inner_html = _render_pptx_runs(para, block, match_map)

    style = f"{align_css}{bullet_indent}"
    return f'<p style="{style}">{inner_html}</p>'


def _render_pptx_runs(
    para: object,
    block: ContentBlock | None,
    match_map: _MatchMap,
) -> str:
    """PowerPoint 段落の run リストを書式 + ハイライト付き HTML に変換する。"""
    positions: list[tuple[int, int]] = []
    if block is not None:
        positions = match_map.get(id(block), [])

    try:
        runs = para.runs  # type: ignore[union-attr]
    except Exception:
        plain = getattr(para, "text", "").strip()
        return _highlight_segments(plain, positions)

    # run ごとの (開始, 終了, run) を構築
    run_spans: list[tuple[int, int, object]] = []
    cursor = 0
    for run in runs:
        t = run.text
        run_spans.append((cursor, cursor + len(t), run))
        cursor += len(t)
    full_text = "".join(r.text for r in runs)

    if not run_spans:
        return _highlight_segments(full_text, positions)

    events: set[int] = {0, len(full_text)}
    for s, e, _ in run_spans:
        events.add(s)
        events.add(e)
    for s, e in positions:
        events.add(max(0, s))
        events.add(min(len(full_text), e))
    sorted_events = sorted(events)

    parts: list[str] = []
    for i in range(len(sorted_events) - 1):
        seg_start = sorted_events[i]
        seg_end = sorted_events[i + 1]
        if seg_start >= seg_end:
            continue
        seg_text = full_text[seg_start:seg_end]
        if not seg_text:
            continue

        run_obj = None
        for rs, re_end, r in run_spans:
            if rs <= seg_start < re_end:
                run_obj = r
                break

        is_highlighted = any(hs < seg_end and he > seg_start for hs, he in positions)
        styles = _get_pptx_run_style_list(run_obj) if run_obj else []
        escaped = html.escape(seg_text)

        if is_highlighted:
            hl_style = (
                "background:#ffeb3b;font-weight:bold;"
                "outline:1px solid #f0c400;padding:1px 2px;border-radius:2px;"
            )
            combined = ";".join(styles) + (";" if styles else "") + hl_style
            parts.append(
                f'<span class="match-highlight" style="{combined}">{escaped}</span>'
            )
        elif styles:
            parts.append(f'<span style="{";".join(styles)}">{escaped}</span>')
        else:
            parts.append(escaped)

    return "".join(parts)


def _get_pptx_run_style_list(run: object) -> list[str]:
    """python-pptx の Run から CSS スタイルリストを返す。"""
    styles: list[str] = []
    try:
        font = run.font  # type: ignore[union-attr]
        if font.bold:
            styles.append("font-weight:bold")
        if font.italic:
            styles.append("font-style:italic")
        if font.underline:
            styles.append("text-decoration:underline")
        if font.size is not None:
            pt = font.size.pt
            if 4 <= pt <= 96:
                styles.append(f"font-size:{pt:.0f}pt")
        if font.color and font.color.type is not None:
            try:
                rgb_val = str(font.color.rgb)[-6:]
                if re.match(r"^[0-9A-Fa-f]{6}$", rgb_val):
                    styles.append(f"color:#{rgb_val}")
            except Exception:
                pass
    except Exception:
        pass
    return styles


def _render_pptx_table(
    table: object,
    block_lookup: "_TextBlockLookup",
    match_map: _MatchMap,
) -> str:
    """PowerPoint テーブルを HTML テーブルにレンダリングする。"""
    parts = [
        '<table style="border-collapse:collapse;width:100%;font-size:0.85em;">'
    ]
    try:
        for ri, row in enumerate(table.rows):  # type: ignore[union-attr]
            parts.append("<tr>")
            for cell in row.cells:
                text = cell.text.strip()
                block = _find_block_by_text(text, block_lookup)
                cell_html = (
                    _highlight_block(block, match_map)
                    if block
                    else html.escape(text)
                )
                tag = "th" if ri == 0 else "td"
                bg = "background:#f5f5f5;" if ri == 0 else ""
                parts.append(
                    f'<{tag} style="border:1px solid #ccc;padding:4px 8px;'
                    f'vertical-align:top;{bg}">{cell_html}</{tag}>'
                )
            parts.append("</tr>")
    except Exception:
        pass
    parts.append("</table>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# テキスト検索 / マッチハイライト ヘルパー
# ---------------------------------------------------------------------------

def _build_text_block_lookup(blocks: list[ContentBlock]) -> _TextBlockLookup:
    """テキスト（strip 済み） → ContentBlock リストのマップを構築する。

    同一テキストのブロックが複数ある場合はリストに全て格納する。
    """
    result: _TextBlockLookup = {}
    for block in blocks:
        key = block.text.strip()
        if key:
            result.setdefault(key, []).append(block)
    return result


def _find_block_by_text(
    text: str,
    block_lookup: _TextBlockLookup,
) -> ContentBlock | None:
    """テキストが一致する最初の ContentBlock を返す。見つからない場合は None。"""
    if not text:
        return None
    candidates = block_lookup.get(text.strip())
    return candidates[0] if candidates else None


def _build_match_map(matches: list[MatchInfo]) -> _MatchMap:
    """MatchInfo リストから ``id(ContentBlock)`` → 位置リストのマップを構築する。"""
    result: _MatchMap = {}
    for m in matches:
        result.setdefault(id(m.block), []).append((m.start, m.end))
    return result


def _highlight_block(block: ContentBlock, match_map: _MatchMap) -> str:
    """ブロック全体をハイライト付きの HTML に変換する（HTML エスケープ安全）。"""
    positions = match_map.get(id(block), [])
    return _highlight_segments(block.text, positions)


def _highlight_segment(
    segment: str,
    full_text: str,
    block: ContentBlock,
    match_map: _MatchMap,
) -> str:
    """full_text 内の部分文字列 segment に対応するハイライト HTML を生成する。"""
    offset = full_text.find(segment)
    if offset < 0:
        return html.escape(segment)
    positions = match_map.get(id(block), [])
    adjusted = [
        (max(0, s - offset), max(0, e - offset))
        for s, e in positions
        if e > offset and s < offset + len(segment)
    ]
    return _highlight_segments(segment, adjusted)


def _highlight_segments(text: str, positions: list[tuple[int, int]]) -> str:
    """テキストを HTML エスケープしながら指定範囲をハイライトする。"""
    if not positions:
        return html.escape(text)

    sorted_pos = sorted(set(positions), key=lambda x: x[0])
    parts: list[str] = []
    prev = 0

    for start, end in sorted_pos:
        start = max(prev, start)
        end = min(len(text), max(start, end))
        if start >= len(text):
            break
        parts.append(html.escape(text[prev:start]))
        parts.append(
            f'<span class="match-highlight">'
            f"{html.escape(text[start:end])}</span>"
        )
        prev = end

    parts.append(html.escape(text[prev:]))
    return "".join(parts)


# ---------------------------------------------------------------------------
# Excel 簡易グリッド（フォールバック用）
# ---------------------------------------------------------------------------

def _render_excel_grid(
    blocks: list[ContentBlock],
    match_map: _MatchMap,
) -> str:
    """セルブロック群からグリッド形式の HTML テーブルを生成する（フォールバック）。"""
    if not blocks:
        return '<p style="color:#aaa;padding:8px;">（データなし）</p>'

    cell_data: dict[tuple[int, int], str] = {}
    max_row = 0
    max_col = 0

    for block in blocks:
        if not block.cell:
            continue
        row, col = _parse_cell_coord(block.cell)
        if row <= 0 or col <= 0:
            continue
        cell_data[(row, col)] = _highlight_block(block, match_map)
        max_row = max(max_row, row)
        max_col = max(max_col, col)

    if not cell_data:
        return '<p style="color:#aaa;padding:8px;">（データなし）</p>'

    parts = ['<div style="overflow-x:auto;"><table class="excel-table">']

    parts.append("<tr><th></th>")
    for c in range(1, max_col + 1):
        parts.append(f"<th>{_col_index_to_letter(c)}</th>")
    parts.append("</tr>")

    for r in range(1, max_row + 1):
        parts.append(f'<tr><td class="row-header">{r}</td>')
        for c in range(1, max_col + 1):
            parts.append(f"<td>{cell_data.get((r, c), '')}</td>")
        parts.append("</tr>")

    parts.append("</table></div>")
    return "\n".join(parts)


def _parse_cell_coord(coord: str) -> tuple[int, int]:
    """セル参照文字列を (row, col) のインデックスに変換する。例: ``"A1"`` → ``(1, 1)``。"""
    m = re.match(r"([A-Za-z]+)(\d+)", coord)
    if not m:
        return (0, 0)
    return (int(m.group(2)), _col_letter_to_index(m.group(1).upper()))


def _col_letter_to_index(letters: str) -> int:
    """列アルファベットを数値インデックスに変換する（1 始まり）。"""
    result = 0
    for ch in letters:
        result = result * 26 + (ord(ch) - ord("A") + 1)
    return result


def _col_index_to_letter(index: int) -> str:
    """列インデックスをアルファベットに変換する（1 始まり）。"""
    result = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


# ---------------------------------------------------------------------------
# Markdown インライン変換
# ---------------------------------------------------------------------------

def _apply_inline_md(text: str) -> str:
    """Markdown インライン要素（``**bold**`` / ``*italic*`` / ``code``）を HTML に変換する。"""
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


# ---------------------------------------------------------------------------
# 共通ユーティリティ
# ---------------------------------------------------------------------------

def _location_header_class(ext: str) -> str:
    """拡張子から位置情報ヘッダーの CSS クラス名を返す。"""
    mapping = {
        "pdf": "pdf-page-header",
        "xlsx": "sheet-label",
        "pptx": "slide-header-bar",
    }
    return mapping.get(ext, "pdf-page-header")


def _wrap_html(body: str, encoding: str | None) -> str:
    """ボディ HTML を完全な HTML ドキュメントでラップする。"""
    badge = (
        f'<div class="encoding-badge">{html.escape(encoding)}</div>'
        if encoding
        else ""
    )
    return (
        "<!DOCTYPE html>\n"
        "<html><head>"
        '<meta charset="utf-8">'
        f"{_BASE_CSS}"
        "</head><body>"
        f"{body}"
        f"{badge}"
        "</body></html>"
    )
