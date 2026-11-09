import re

import pytest

from src.enumeration import FileInfo
from src.extraction import extract_file
from src.preview import PreviewRenderer, build_preview
from src.preview.converter import available_backends, patch_sheet_xml
from src.preview.page_document import PageDocument, PageLayout
from src.search import CompiledQuery, SearchOptions

needs_converter = pytest.mark.skipif(
    not available_backends(), reason="Microsoft Office / LibreOffice が必要"
)


def query(text: str, **options) -> CompiledQuery:
    return CompiledQuery(SearchOptions(query=text, **options))


def test_pdf_hits_have_rects_and_span_wrapped_lines(sample_dir):
    document = PageDocument(sample_dir / "sample.pdf")
    try:
        hits, truncated = document.find_hits(query("banana"))
        assert [h.page for h in hits] == [0, 0, 1] and not truncated
        for hit in hits:
            for x0, y0, x1, y1 in hit.rects:
                assert 0 <= x0 < x1 <= document.layouts[hit.page].width
                assert 0 <= y0 < y1 <= document.layouts[hit.page].height
        
        # 行をまたぐ語句は行ごとの矩形に分かれる
        wrapped, _ = document.find_hits(query("fox jumps over the lazy dog", term_mode="phrase"))
        assert len(wrapped) == 1 and len(wrapped[0].rects) >= 2
        
        limited, truncated = document.find_hits(query("banana"), max_hits=2)
        assert len(limited) == 2 and truncated
        
        png = document.render_tile(0, 0)
        assert png.startswith(b"\x89PNG")
        assert document.render_tile(5, 0) is None
    finally:
        document.close()


def test_large_page_is_split_into_tiles():
    layout = PageLayout((0, 0, 3000, 5000))
    assert layout.cols == 3 and layout.rows == 5
    left, top, right, bottom = layout.tile_rect(layout.tile_count - 1)
    assert right == pytest.approx(3000) and bottom == pytest.approx(5000)
    
    zoomed = PageLayout((10, 20, 110, 220), zoom=2.0)
    assert (zoomed.width, zoomed.height) == (200, 400)
    assert zoomed.to_display((10, 20, 60, 120)) == (0, 0, 100, 200)


def test_page_view_html(sample_dir):
    document = PageDocument(sample_dir / "sample.pdf")
    try:
        hits, _ = document.find_hits(query("banana"))
        html, preview_hits = PreviewRenderer().render_pages(document, hits, "tile")
        assert html.count("class='page'") == 2
        assert "src='tile/0/0.png'" in html and "src='tile/1/0.png'" in html
        assert len(set(re.findall(r"data-hit='(\d+)'", html))) == 3
        assert preview_hits[2].label == "ページ 2" and "【BANANA】" in preview_hits[2].text
    finally:
        document.close()


def test_text_view_marks_hits_and_escapes(sample_dir):
    content = extract_file(str(sample_dir / "notes.md"))
    html, hits, truncated = PreviewRenderer().render_text(content, query("バナナ tag", term_mode="or"))
    assert len(hits) == 2 and not truncated
    assert "<mark class='hit' data-hit='0'>バナナ</mark>" in html
    assert "&lt;b&gt;<mark class='hit' data-hit='1'>tag</mark>&lt;/b&gt;" in html
    assert "utf-8" in html


def test_text_view_keeps_line_numbers(sample_dir):
    content = extract_file(str(sample_dir / "memo.txt"))
    html, hits, _ = PreviewRenderer().render_text(content, query("四行目"))
    gutter = re.search(r"<pre class='gutter'>(.*?)</pre>", html, re.S).group(1)
    assert gutter.split("\n") == ["1", "2", "3", "4", "5"]
    assert hits[0].label == "行 4"


def test_text_view_excel_grid_and_shapes(sample_dir):
    content = extract_file(str(sample_dir / "sample.xlsx"))
    html, hits, _ = PreviewRenderer().render_text(content, query("バナナ"))
    assert len(hits) == 3
    assert "<th>A</th><th>B</th><th>C</th>" in html
    assert "<th class='row'>4</th><td>検索対象<mark" in html
    assert "図形（B9 付近）" in html
    assert {h.label for h in hits} == {"シート: 売上, セル A4", "シート: 売上, 図形", "シート: メモ, セル B40"}


def test_text_view_hit_limit(sample_dir):
    content = extract_file(str(sample_dir / "sample.docx"))
    _, hits, truncated = PreviewRenderer().render_text(content, query("バナナ"), max_hits=2)
    assert len(hits) == 2 and truncated


def test_patch_sheet_xml_sets_print_options():
    xml = (
        '<worksheet xmlns="x"><sheetPr><tabColor rgb="FF0000"/></sheetPr>'
        '<sheetViews><sheetView showGridLines="0" workbookViewId="0"/></sheetViews>'
        "<sheetData/>"
        '<printOptions horizontalCentered="1"/>'
        '<pageMargins left="1" right="1" top="1" bottom="1" header="0.5" footer="0.5"/>'
        '<pageSetup paperSize="9" orientation="portrait"/>'
        "<headerFooter><oddFooter>&amp;P</oddFooter></headerFooter>"
        '<rowBreaks count="1"><brk id="10"/></rowBreaks>'
        '<drawing r:id="rId1"/></worksheet>'
    )
    patched = patch_sheet_xml(xml)
    assert '<sheetPr><tabColor rgb="FF0000"/><pageSetUpPr fitToPage="1"/></sheetPr>' in patched
    # 枠線を非表示にしているシートでは枠線を出さない
    assert '<printOptions gridLines="0" headings="1"/>' in patched
    assert "headerFooter" not in patched and "rowBreaks" not in patched
    assert patched.count("<pageSetup ") == 1 and 'fitToWidth="1"' in patched
    # 印刷設定は drawing より前に置く（スキーマの並び順）
    assert patched.index("<pageSetup ") < patched.index("<drawing ")
    
    minimal = patch_sheet_xml('<worksheet xmlns="x"><sheetData/></worksheet>')
    assert minimal.startswith('<worksheet xmlns="x"><sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>')
    assert '<printOptions gridLines="1" headings="1"/>' in minimal
    assert patch_sheet_xml("<chartsheet/>") == "<chartsheet/>"


def test_build_preview_text_and_pdf(sample_dir):
    options = SearchOptions(query="バナナ")
    preview = build_preview(FileInfo.from_path(sample_dir / "memo.txt"), options)
    assert preview.mode == "text" and len(preview.hits) == 1 and not preview.page_mode_available
    
    preview = build_preview(FileInfo.from_path(sample_dir / "sample.pdf"), SearchOptions(query="banana"))
    try:
        assert preview.mode == "page" and len(preview.hits) == 3
    finally:
        preview.page_document.close()


def test_build_preview_falls_back_to_text_without_converter(sample_dir, isolated_config):
    isolated_config.office_converter = "none"
    preview = build_preview(FileInfo.from_path(sample_dir / "sample.xlsx"), SearchOptions(query="バナナ"))
    assert preview.mode == "text" and len(preview.hits) == 3
    assert "テキスト表示" in preview.note and not preview.page_mode_available


@needs_converter
def test_build_preview_excel_page_view_includes_shapes(sample_dir):
    preview = build_preview(FileInfo.from_path(sample_dir / "sample.xlsx"), SearchOptions(query="バナナ"))
    try:
        assert preview.mode == "page" and preview.note == ""
        document = preview.page_document
        assert document.labels == ["シート: 売上", "シート: メモ"]
        texts = [h.text for h in preview.hits]
        assert any("図形の中の【バナナ】注記" in t for t in texts)  # 図形内の文字も強調される
        assert [h.label for h in preview.hits].count("シート: メモ") == 1
        assert document.render_tile(0, 0).startswith(b"\x89PNG")
    finally:
        preview.page_document.close()


@needs_converter
def test_build_preview_word_and_powerpoint_page_view(sample_dir):
    for name, labels in (("sample.docx", ["ページ 1"]), ("sub/sample.pptx", ["スライド 1", "スライド 2"])):
        preview = build_preview(FileInfo.from_path(sample_dir / name), SearchOptions(query="バナナ"))
        try:
            assert preview.mode == "page", preview.note
            assert preview.page_document.labels == labels
            assert preview.hits
        finally:
            preview.page_document.close()
