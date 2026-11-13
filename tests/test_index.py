"""検索インデックス・バックグラウンド更新・旧形式の Office"""

import subprocess

import pytest

from src.enumeration import FileEnumerator
from src.extraction import extract_file
from src.extraction.cache import get_extraction_cache
from src.preview.converter import find_libreoffice
from src.search import Searcher, SearchOptions


def search(folder, **options):
    files = FileEnumerator().enumerate(folder).files
    results = []
    summary = Searcher().search_files(files, SearchOptions(**options), result_callback=results.append)
    return summary, {r.file_info.name: r.match_count for r in results if not r.error}


@pytest.mark.parametrize("options", [
    {"query": "バナナ"},
    {"query": "banana"},
    {"query": "BANANA", "case_sensitive": True},
    {"query": "ｂａｎａｎａ"},  # 全角でも見つかる
    {"query": "在庫"},  # 3文字未満（索引の全文走査で絞り込む）
    {"query": "バナナ りんご"},
    {"query": "バナナ みかん", "term_mode": "or"},
    {"query": r"バ.ナ", "use_regex": True},
    {"query": "存在しない語句"},
])
def test_index_filtering_gives_same_results(sample_dir, options):
    first, expected = search(sample_dir, **options)  # 索引を作る
    second, results = search(sample_dir, **options)  # 索引で絞り込む
    assert results == expected
    assert second.cache_hits == second.total_files
    if not options.get("use_regex"):
        # 索引は「含む可能性のあるファイル」を漏れなく残し、確実に含まないものだけを除く
        assert 0 < second.skipped_by_index <= second.total_files - len(results) or len(results) == second.total_files


def test_index_detects_changed_and_deleted_files(sample_dir):
    search(sample_dir, query="バナナ")
    (sample_dir / "memo.txt").write_text("バナナ バナナ バナナ", encoding="utf-8")
    (sample_dir / "notes.md").unlink()
    summary, results = search(sample_dir, query="バナナ")
    assert results["memo.txt"] == 3 and "notes.md" not in results
    assert summary.cache_hits == summary.total_files - 1  # 変更された memo.txt は読み直す


def test_background_indexer_builds_index(sample_dir):
    from src.index import IndexWorker
    
    worker = IndexWorker()
    finished = []
    worker.finished.connect(finished.append)
    worker.run([str(sample_dir)], True)
    status = finished[-1]
    assert not status.running and status.indexed_files == 6 and status.last_finished
    
    summary, _ = search(sample_dir, query="バナナ")
    assert summary.cache_hits == summary.total_files  # 1回目の検索から索引が使える
    
    # 削除されたファイルは次の更新で索引から除かれる
    (sample_dir / "memo.txt").unlink()
    worker.run([str(sample_dir)], True)
    cache = get_extraction_cache()
    assert not any(p.endswith("memo.txt") for p in cache.indexed_paths_under(sample_dir))


def test_index_does_not_mix_sibling_folders(tmp_path):
    from src.extraction.cache import ExtractionCache
    from src.extraction import ContentBlock, ExtractedContent
    
    cache = ExtractionCache(tmp_path / "i.sqlite")
    for folder in ("docs", "docs2"):
        path = tmp_path / folder / "a.txt"
        cache.put(path, 1, 1, ExtractedContent(file_path=path, blocks=[ContentBlock("x")]))
    assert [p for p in cache.indexed_paths_under(tmp_path / "docs")] == [str(tmp_path / "docs" / "a.txt")]
    cache.close()


needs_libreoffice = pytest.mark.skipif(find_libreoffice() is None, reason="LibreOffice が必要")


@needs_libreoffice
def test_legacy_office_formats(sample_dir, tmp_path):
    """LibreOffice で作った .xls / .doc / .ppt から文字を取り出せる"""
    profile = (tmp_path / "lo").resolve().as_uri()
    sources = [("sample.xlsx", "xls"), ("sample.docx", "doc"), ("sub/sample.pptx", "ppt")]
    out = tmp_path / "legacy"
    out.mkdir()
    for name, target in sources:
        subprocess.run(
            [find_libreoffice(), "--headless", "--norestore", f"-env:UserInstallation={profile}",
             "--convert-to", target, "--outdir", str(out), str(sample_dir / name)],
            capture_output=True, timeout=180, check=False,
        )
    
    xls = extract_file(str(out / "sample.xls"))
    assert not xls.error and xls.total_sheets == 2
    cells = {(b.sheet, b.cell): b.text for b in xls.blocks}
    assert cells[("売上", "A4")] == "検索対象バナナ" and cells[("売上", "B2")] == "10"
    
    doc = extract_file(str(out / "sample.doc"))
    texts = [b.text for b in doc.blocks]
    assert not doc.error and "報告書" in texts and "バナナ在庫" in texts
    assert any(b.kind == "header" and "バナナ" in b.text for b in doc.blocks)
    
    ppt = extract_file(str(out / "sample.ppt"))
    assert not ppt.error and ppt.total_slides == 2
    assert any(b.slide == 1 and "バナナ戦略" in b.text for b in ppt.blocks)
    assert any(b.slide == 2 and b.kind == "note" and "バナナ" in b.text for b in ppt.blocks)
    
    _, results = search(out, query="バナナ")
    assert set(results) == {"sample.xls", "sample.doc", "sample.ppt"}


def test_legacy_broken_files_report_errors(tmp_path):
    for name in ("a.xls", "b.doc", "c.ppt"):
        (tmp_path / name).write_bytes(b"not an office file")
        assert extract_file(str(tmp_path / name)).error


def test_worker_count_uses_logical_processors(isolated_config, monkeypatch):
    from src.search import searcher
    
    monkeypatch.setattr(searcher, "logical_processors", lambda: 16)
    isolated_config.search_workers = 0
    assert searcher.worker_count() == 15
    isolated_config.search_workers = 4
    assert searcher.worker_count() == 4
