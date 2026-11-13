"""自己診断（実行ファイルの動作確認用）

使い方: UnifiedFileSearch.exe --self-test 結果.json

一時フォルダにサンプルの Office / PDF / テキストを作り、次を確かめて結果を JSON に書き出す。
終了コードは、すべて成功なら 0、失敗があれば 1。

1. 並列抽出（ワーカープロセス）を使った検索
2. PDF の原本表示（ページ画像の描画とヒット位置）
3. Office ファイルの原本表示（変換エンジンがある場合のみ）
4. 画面（メインウィンドウ）の起動
"""

import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path


def _write_pdf(path: Path) -> None:
    """Helvetica だけを使う最小限の PDF"""
    lines = [(72, 72, "Self test banana page one"), (72, 86, "second line with BANANA")]
    stream = b"".join(
        b"BT /F1 12 Tf %d %d Td (%s) Tj ET\n" % (x, 792 - y - 12, text.encode("latin-1"))
        for x, y, text in lines
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 3 0 R >> >> /Contents 5 0 R >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    path.write_bytes(bytes(out))


def make_samples(folder: Path) -> dict[str, int]:
    """サンプルファイルを作り、ファイル名 → 期待するヒット数 を返す"""
    from docx import Document
    from openpyxl import Workbook
    from pptx import Presentation
    from pptx.util import Inches
    
    expected: dict[str, int] = {}
    
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "売上"
    sheet.append(["商品", "数量"])
    sheet.append(["バナナ", 10])
    sheet.append(["りんご", 20])
    workbook.create_sheet("メモ")["B5"] = "下の方のバナナ"
    workbook.save(folder / "sample.xlsx")
    expected["sample.xlsx"] = 2
    
    document = Document()
    document.add_heading("報告書", 1)
    document.add_paragraph("これはバナナの報告です。")
    table = document.add_table(rows=2, cols=2)
    for r in range(2):
        for c in range(2):
            table.cell(r, c).text = f"セル{r}{c}"
    table.cell(1, 1).text = "バナナ在庫"
    document.save(folder / "sample.docx")
    expected["sample.docx"] = 2
    
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = "バナナ戦略"
    box = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(5), Inches(1))
    box.text_frame.text = "図形の中のバナナ"
    presentation.save(folder / "sample.pptx")
    expected["sample.pptx"] = 2
    
    _write_pdf(folder / "sample.pdf")
    expected["sample.pdf"] = 2
    
    # 並列抽出を使わせるため、テキストファイルを多めに置く
    for i in range(10):
        (folder / f"memo{i}.txt").write_bytes(f"{i}行目\nバナナ {i}\n".encode("cp932"))
        expected[f"memo{i}.txt"] = 1
    return expected


def run(report_path: Path) -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    
    report: dict = {"steps": [], "ok": True, "platform": sys.platform, "frozen": bool(getattr(sys, "frozen", False))}
    
    def step(name: str, func) -> None:
        started = time.time()
        try:
            detail = func()
            report["steps"].append({"name": name, "ok": True, "seconds": round(time.time() - started, 2), "detail": detail})
        except Exception:
            report["ok"] = False
            report["steps"].append({"name": name, "ok": False, "error": traceback.format_exc()})
    
    from src import __version__
    from src.common.config import get_config
    
    report["version"] = __version__
    config = get_config()
    config.search_workers = 2  # ワーカープロセスを必ず使う
    
    with tempfile.TemporaryDirectory(prefix="ufst_selftest_") as tmp:
        folder = Path(tmp)
        expected = make_samples(folder)
        
        def search():
            from src.enumeration import FileEnumerator
            from src.search import Searcher, SearchOptions, shutdown_pool
            
            config.extraction_cache_enabled = False
            files = FileEnumerator().enumerate(folder).files
            results = []
            summary = Searcher().search_files(
                files, SearchOptions(query="バナナ banana", term_mode="or"), result_callback=results.append
            )
            shutdown_pool()
            counts = {r.file_info.name: r.match_count for r in results}
            errors = {r.file_info.name: r.error for r in results if r.error}
            assert not errors, f"読み込みエラー: {errors}"
            assert counts == expected, f"ヒット数が違います: {counts} != {expected}"
            return {"files": summary.total_files, "matches": summary.total_matches}
        
        def pdf_preview():
            from src.enumeration import FileInfo
            from src.preview import build_preview
            from src.search import SearchOptions
            
            preview = build_preview(FileInfo.from_path(folder / "sample.pdf"), SearchOptions(query="banana"))
            try:
                assert preview.mode == "page", preview.note
                assert len(preview.hits) == 2, len(preview.hits)
                png = preview.page_document.render_tile(0, 0)
                assert png and png.startswith(b"\x89PNG")
            finally:
                if preview.page_document:
                    preview.page_document.close()
            return {"hits": len(preview.hits), "png_bytes": len(png)}
        
        def office_preview():
            from src.enumeration import FileInfo
            from src.preview import build_preview
            from src.preview.converter import available_backends
            from src.search import SearchOptions
            
            backends = available_backends()
            if not backends:
                return {"skipped": "変換エンジンがありません"}
            detail = {"backends": backends}
            for name in ("sample.xlsx", "sample.docx", "sample.pptx"):
                preview = build_preview(FileInfo.from_path(folder / name), SearchOptions(query="バナナ"))
                try:
                    assert preview.mode == "page", f"{name}: {preview.note}"
                    assert preview.hits, f"{name}: ヒットが見つかりません"
                    detail[name] = {"hits": len(preview.hits), "labels": preview.sections}
                finally:
                    if preview.page_document:
                        preview.page_document.close()
            return detail
        
        def window():
            from PySide6.QtCore import QEventLoop, QTimer
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance() or QApplication([sys.argv[0]])
            from src.ui import MainWindow
            from src.ui.settings import UserSettings
            from src.ui.theme import theme
            from PySide6.QtCore import QSettings
            
            settings = UserSettings(QSettings(str(folder / "settings.ini"), QSettings.Format.IniFormat))
            theme().apply(app)
            from src.licensing.manager import LicenseManager
            main = MainWindow(settings, LicenseManager(folder / "window_license.json"))
            main.show()
            main._search_bar.set_folder(str(folder))
            
            def wait(ms):
                loop = QEventLoop()
                QTimer.singleShot(ms, loop.quit)
                loop.exec()
            
            deadline = time.time() + 30
            while main._listing_root is None and time.time() < deadline:
                wait(100)
            assert main._listing_root is not None, "ファイル一覧が表示されません"
            listed = main._results._proxy.rowCount()
            
            # 原本表示（ページ画像）とテキストファイル表示が実際に描画されること
            from src.enumeration import FileInfo
            from src.preview import build_preview
            from src.search import SearchOptions
            
            pdf = FileInfo.from_path(folder / "sample.pdf")
            main._preview.set_preview(pdf, build_preview(pdf, SearchOptions(query="banana")))
            view = main._preview._page_view
            deadline = time.time() + 20
            while not view._cache and time.time() < deadline:
                wait(100)
            assert view._cache, "ページ画像が描画されません"
            assert main._preview._position.text() == "1 / 2", main._preview._position.text()
            memo = FileInfo.from_path(folder / "memo0.txt")
            main._preview.set_preview(memo, build_preview(memo, SearchOptions(query="バナナ")))
            assert main._preview._mode == "plain" and main._preview._plain_view.blockCount() >= 2
            from src.ui import icons
            assert not icons.app_icon().isNull(), "アプリのアイコンが読み込めません"
            assert "#Card" in app.styleSheet(), "テーマが適用されていません"
            main.close()
            wait(200)
            return {"listed_files": listed}
        
        def licensing():
            from datetime import date, timedelta
            from src.licensing.codec import generate_private_key, issue_code, public_key_b64
            from src.licensing.manager import LicenseManager
            from src.licensing.public_key import PUBLIC_KEY_B64
            
            # 使い捨ての鍵で、署名・検証・体験期間の判定が実行ファイルの中で動くことを確かめる
            key = generate_private_key()
            storage = folder / "license.json"
            today = date(2026, 1, 1)
            manager = LicenseManager(storage, public_key_b64(key), today=today)
            assert manager.state().status == "trial"
            assert LicenseManager(storage, public_key_b64(key), today=today + timedelta(days=400)).state().status == "expired"
            manager.activate("自己診断", issue_code(key, "自己診断", 1))
            assert LicenseManager(storage, public_key_b64(key)).state().status == "licensed"
            return {"public_key_configured": bool(PUBLIC_KEY_B64)}
        
        step("search", search)
        step("licensing", licensing)
        step("pdf_preview", pdf_preview)
        step("office_preview", office_preview)
        step("window", window)
    
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
