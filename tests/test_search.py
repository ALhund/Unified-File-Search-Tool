from pathlib import Path

import pytest

from src.enumeration import FileEnumerator
from src.extraction import ContentBlock, ExtractedContent, extract_file
from src.search import (
    CompiledQuery,
    QueryError,
    Searcher,
    SearchOptions,
    search_content,
    split_terms,
)


def content_of(*texts: str) -> ExtractedContent:
    return ExtractedContent(
        file_path=Path("x.txt"),
        blocks=[ContentBlock(text=t, line=i + 1) for i, t in enumerate(texts)],
    )


def find(content, max_matches=50, **options):
    return search_content(content, CompiledQuery(SearchOptions(**options)), max_matches)


def test_split_terms():
    assert split_terms('foo  "bar baz"　qux foo') == ["foo", "bar baz", "qux"]


def test_case_and_width_insensitive_by_default():
    matches, _ = find(content_of("Banana ＢＡＮＡＮＡ ﾊﾞﾅﾅ"), query="banana")
    assert [m.matched_text for m in matches] == ["Banana", "ＢＡＮＡＮＡ"]
    matches, _ = find(content_of("Banana ＢＡＮＡＮＡ ﾊﾞﾅﾅ"), query="バナナ")
    assert [m.matched_text for m in matches] == ["ﾊﾞﾅﾅ"]


def test_case_and_width_sensitive():
    matches, _ = find(
        content_of("Banana banana ｂａｎａｎａ"), query="banana", case_sensitive=True, ignore_width=False
    )
    assert [(m.start, m.matched_text) for m in matches] == [(7, "banana")]


def test_and_requires_all_terms_in_file():
    content = content_of("りんご", "バナナ")
    assert len(find(content, query="りんご バナナ")[0]) == 2
    assert find(content, query="りんご みかん")[0] == []
    assert len(find(content, query="りんご みかん", term_mode="or")[0]) == 1


def test_and_checks_remaining_terms_after_limit():
    content = content_of(*["りんご"] * 10, "バナナ")
    matches, truncated = find(content, max_matches=3, query="りんご バナナ")
    assert len(matches) == 3 and truncated


def test_phrase_mode_keeps_spaces():
    content = content_of("red apple", "apple red")
    matches, _ = find(content, query="red apple", term_mode="phrase")
    assert [m.block_index for m in matches] == [0]


def test_limit_and_truncation_flag():
    matches, truncated = find(content_of("aaaa"), max_matches=4, query="a")
    assert len(matches) == 4 and not truncated
    matches, truncated = find(content_of("aaaaa"), max_matches=4, query="a")
    assert len(matches) == 4 and truncated


def test_exclude_words_skip_block():
    matches, _ = find(content_of("バナナ在庫", "バナナ出荷"), query="バナナ", exclude_words=["在庫"])
    assert [m.block_index for m in matches] == [1]


def test_match_whole():
    matches, _ = find(content_of("バナナ", " バナナ ", "バナナ在庫"), query="バナナ", match_whole=True)
    assert [m.block_index for m in matches] == [0, 1]
    assert matches[1].matched_text == "バナナ"


def test_regex():
    matches, _ = find(content_of("注文 A-123 と b-45"), query=r"[a-z]-\d+", use_regex=True)
    assert [m.matched_text for m in matches] == ["A-123", "b-45"]
    matches, _ = find(content_of("abc"), query=r"x*", use_regex=True)
    assert matches == []  # 空文字へのマッチは無視
    with pytest.raises(QueryError):
        CompiledQuery(SearchOptions(query="(", use_regex=True))
    with pytest.raises(QueryError):
        CompiledQuery(SearchOptions(query="   "))


def test_context_snippet():
    matches, _ = find(content_of("x" * 100 + "バナナ" + "y" * 100), query="バナナ")
    assert matches[0].before.startswith("…") and matches[0].after.endswith("…")
    assert "バナナ" in matches[0].snippet


def test_enumerator_filters(sample_dir):
    result = FileEnumerator().enumerate(sample_dir, target_extensions={"xlsx", ".TXT"})
    assert sorted(f.name for f in result.files) == ["memo.txt", "sample.xlsx"]
    flat = FileEnumerator().enumerate(sample_dir, include_subfolders=False)
    assert "sample.pptx" not in [f.name for f in flat.files]


def test_extract_excel_cells_shapes_and_charts(sample_dir):
    content = extract_file(str(sample_dir / "sample.xlsx"))
    by_kind = {(b.kind, b.sheet, b.cell): b.text for b in content.blocks}
    assert by_kind[(None, "売上", "A4")] == "検索対象バナナ"
    assert by_kind[(None, "売上", "B2")] == "10"
    assert by_kind[("shape", "売上", "B9")] == "図形の中のバナナ注記"
    assert any(b.kind == "chart" and "数量グラフ" in b.text for b in content.blocks)


def test_extract_word_in_document_order(sample_dir):
    content = extract_file(str(sample_dir / "sample.docx"))
    texts = [b.text for b in content.blocks]
    assert texts[0] == "ヘッダーのバナナ" and content.blocks[0].kind == "header"
    assert texts.index("報告書") < texts.index("バナナ在庫")
    cell = next(b for b in content.blocks if b.text == "バナナ在庫")
    assert cell.table == (0, 1, 0)


def test_extract_powerpoint_notes(sample_dir):
    content = extract_file(str(sample_dir / "sub" / "sample.pptx"))
    assert content.total_slides == 2
    assert any(b.kind == "note" and b.slide == 2 for b in content.blocks)


def test_extract_pdf_joins_wrapped_lines(sample_dir):
    content = extract_file(str(sample_dir / "sample.pdf"))
    assert content.total_pages == 2
    assert any("lazy dog and eats a banana" in " ".join(b.text.split()) for b in content.blocks)


def test_text_encoding_detection(sample_dir):
    assert extract_file(str(sample_dir / "memo.txt")).encoding == "cp932"
    assert extract_file(str(sample_dir / "notes.md")).encoding == "utf-8"
    assert extract_file(str(sample_dir / "memo.txt")).total_lines == 5


def run_search(folder, **options):
    files = FileEnumerator().enumerate(folder).files
    results = []
    summary = Searcher().search_files(files, SearchOptions(**options), result_callback=results.append)
    return summary, {r.file_info.name: r for r in results}


def test_search_folder_and_cache(sample_dir):
    summary, results = run_search(sample_dir, query="バナナ")
    assert summary.total_files == 6 and summary.cache_hits == 0
    assert set(results) == {
        "sample.xlsx", "sample.docx", "sample.pptx", "memo.txt", "notes.md",
    }
    assert results["sample.xlsx"].match_count == 3  # セル2件 + 図形1件
    assert "図形" in [m.location for m in results["sample.xlsx"].matches][-1]
    
    # 2回目は抽出結果キャッシュが使われ、結果は同じ
    summary2, results2 = run_search(sample_dir, query="バナナ")
    assert summary2.cache_hits == 6
    assert {n: r.match_count for n, r in results2.items()} == {
        n: r.match_count for n, r in results.items()
    }
    
    # ファイルを更新するとキャッシュは使われない
    (sample_dir / "memo.txt").write_text("バナナ バナナ", encoding="utf-8")
    summary3, results3 = run_search(sample_dir, query="バナナ")
    assert summary3.cache_hits == 5
    assert results3["memo.txt"].match_count == 2


def test_search_reports_broken_file(sample_dir):
    (sample_dir / "broken.xlsx").write_bytes(b"not a zip")
    summary, results = run_search(sample_dir, query="バナナ")
    assert summary.error_files == 1
    assert results["broken.xlsx"].error


def test_parallel_extraction_matches_serial(sample_dir, isolated_config):
    for i in range(10):
        (sample_dir / f"extra{i}.txt").write_text(f"バナナ {i}\n" * (i + 1), encoding="utf-8")
    isolated_config.extraction_cache_enabled = False
    
    isolated_config.search_workers = 1
    serial, serial_results = run_search(sample_dir, query="バナナ")
    isolated_config.search_workers = 2
    try:
        parallel, parallel_results = run_search(sample_dir, query="バナナ")
    finally:
        from src.search import shutdown_pool
        shutdown_pool()
    
    assert parallel.total_matches == serial.total_matches
    assert {n: r.match_count for n, r in parallel_results.items()} == {
        n: r.match_count for n, r in serial_results.items()
    }


def test_unlimited_matches():
    matches, truncated = find(content_of("a" * 300), max_matches=0, query="a")
    assert len(matches) == 300 and not truncated


def test_search_files_respects_explicit_limit(sample_dir):
    files = FileEnumerator().enumerate(sample_dir).files
    results = []
    Searcher().search_files(files, SearchOptions(query="バナナ"), max_matches=1, result_callback=results.append)
    by_name = {r.file_info.name: r for r in results}
    assert by_name["sample.xlsx"].match_count == 1 and by_name["sample.xlsx"].truncated
    assert by_name["sample.xlsx"].display_count == "1+"


def test_word_table_keeps_every_cell(tmp_path):
    """結合セルの重複除去で、別のセルを読み飛ばさないこと（id() 再利用の回帰テスト）"""
    from docx import Document
    
    document = Document()
    table = document.add_table(rows=4, cols=3)
    for r in range(4):
        for c in range(3):
            table.cell(r, c).text = f"セル{r}{c}"
    merged = document.add_table(rows=2, cols=2)
    merged.cell(0, 0).merge(merged.cell(0, 1)).text = "結合"
    merged.cell(1, 0).text = "下左"
    merged.cell(1, 1).text = "下右"
    path = tmp_path / "table.docx"
    document.save(path)
    
    texts = [b.text for b in extract_file(str(path)).blocks]
    assert [t for t in texts if t.startswith("セル")] == [f"セル{r}{c}" for r in range(4) for c in range(3)]
    assert texts.count("結合") == 1 and "下左" in texts and "下右" in texts


def test_powerpoint_chart_text_is_searchable(tmp_path):
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches
    
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    data = CategoryChartData()
    data.categories = ["4月", "5月"]
    data.add_series("出荷数", (1, 2))
    chart = slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(1), Inches(1), Inches(4), Inches(3), data
    ).chart
    chart.has_title = True
    chart.chart_title.text_frame.text = "バナナ月別出荷"
    path = tmp_path / "chart.pptx"
    presentation.save(path)
    
    block = next(b for b in extract_file(str(path)).blocks if b.kind == "chart")
    assert "バナナ月別出荷" in block.text and "出荷数" in block.text and "4月" in block.text
