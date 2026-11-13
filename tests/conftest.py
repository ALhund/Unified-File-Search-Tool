"""テスト共通設定"""

import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """ログ・キャッシュをテスト用の一時フォルダに向ける"""
    from src.common import config as config_module
    from src.common import logger as logger_module
    from src.extraction import cache as cache_module
    
    config = config_module.Config()
    config._config_path = tmp_path / "Config" / "config.xml"
    config._logs_path = tmp_path / "logs"
    config._cache_path = tmp_path / "cache"
    config._logs_path.mkdir()
    config._cache_path.mkdir()
    
    monkeypatch.setattr(config_module, "_config_instance", config)
    monkeypatch.setattr(logger_module, "_loggers", {})
    monkeypatch.setattr(cache_module, "_cache", None)
    yield config
    if cache_module._cache is not None:
        cache_module._cache.close()


# 図形（角丸四角形のテキストボックス）を表す drawing XML
_SHAPE_XML = (
    '<xdr:twoCellAnchor xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
    "<xdr:from><xdr:col>1</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>8</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>"
    "<xdr:to><xdr:col>3</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>13</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>"
    '<xdr:sp macro="" textlink=""><xdr:nvSpPr><xdr:cNvPr id="99" name="Shape 99"/><xdr:cNvSpPr/></xdr:nvSpPr>'
    '<xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="100" cy="100"/></a:xfrm>'
    '<a:prstGeom prst="roundRect"><a:avLst/></a:prstGeom>'
    '<a:solidFill><a:srgbClr val="C6E0B4"/></a:solidFill></xdr:spPr>'
    "<xdr:txBody><a:bodyPr/><a:p><a:r><a:t>図形の中のバナナ注記</a:t></a:r></a:p></xdr:txBody></xdr:sp>"
    "<xdr:clientData/></xdr:twoCellAnchor>"
)


def make_xlsx(path: Path) -> Path:
    """セル・グラフ・図形を含むExcelファイルを作る"""
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference
    
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "売上"
    sheet.append(["商品", "数量", "金額"])
    for i, name in enumerate(["りんご", "みかん", "検索対象バナナ", "ぶどう"]):
        sheet.append([name, (i + 1) * 10, (i + 1) * 1234.5])
    chart = BarChart()
    chart.add_data(Reference(sheet, min_col=2, min_row=1, max_row=5), titles_from_data=True)
    chart.title = "数量グラフ"
    sheet.add_chart(chart, "E8")
    
    memo = workbook.create_sheet("メモ")
    memo["B3"] = "ＡＢＣ全角と ｶﾀｶﾅ 半角"
    memo["B40"] = "下の方のバナナ"
    
    temp = path.with_suffix(".tmp.xlsx")
    workbook.save(temp)
    
    # openpyxl は図形を書き出せないため、drawing XML に直接追加する
    with zipfile.ZipFile(temp) as zin, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "xl/drawings/drawing1.xml":
                text = data.decode("utf-8")
                end = text.rindex("</")
                data = (text[:end] + _SHAPE_XML + text[end:]).encode("utf-8")
            zout.writestr(item, data)
    temp.unlink()
    return path


def make_docx(path: Path) -> Path:
    from docx import Document
    
    document = Document()
    document.add_heading("報告書", 1)
    document.add_paragraph("これはバナナに関する報告です。Banana と banana。")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "項目"
    table.cell(0, 1).text = "値"
    table.cell(1, 0).text = "バナナ在庫"
    table.cell(1, 1).text = "42"
    document.sections[0].header.paragraphs[0].text = "ヘッダーのバナナ"
    document.save(path)
    return path


def make_pptx(path: Path) -> Path:
    from pptx import Presentation
    from pptx.util import Inches
    
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "バナナ戦略"
    slide.placeholders[1].text = "第一に、バナナ。\n第二に、りんご。"
    
    slide2 = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide2.shapes.title.text = "まとめ"
    box = slide2.shapes.add_textbox(Inches(1), Inches(2), Inches(5), Inches(1))
    box.text_frame.text = "BANANA は重要"
    slide2.notes_slide.notes_text_frame.text = "ノートにもバナナ"
    presentation.save(path)
    return path


def write_pdf(path: Path, pages: list[list[tuple[float, float, float, str]]]) -> Path:
    """最小限のPDFを書き出す（テスト用。各ページは (x, 上からのy, 文字サイズ, 文字列) の並び）"""
    width, height = 612, 792
    objects: list[bytes] = []
    
    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)
    
    catalog = add(b"")  # 後で埋める
    pages_obj = add(b"")
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    page_ids = []
    for items in pages:
        stream = b"".join(
            b"BT /F1 %.1f Tf %.1f %.1f Td (%s) Tj ET\n"
            % (size, x, height - y - size, text.encode("latin-1"))
            for x, y, size, text in items
        )
        content = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
        page_ids.append(add(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] "
            b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
            % (pages_obj, width, height, font, content)
        ))
    objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_obj
    objects[pages_obj - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % i for i in page_ids), len(page_ids))
    
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, catalog, xref)
    path.write_bytes(bytes(out))
    return path


def make_pdf(path: Path) -> Path:
    """2ページのPDF（1ページ目は語句が行をまたぐ段落）"""
    return write_pdf(path, [
        [
            (72, 72, 12, "Hello banana world."),
            (72, 86, 12, "The quick brown fox jumps over the"),
            (72, 100, 12, "lazy dog and eats a banana."),
        ],
        [(72, 100, 14, "Second page BANANA")],
    ])


@pytest.fixture
def sample_dir(tmp_path) -> Path:
    """各形式のサンプルファイルを置いたフォルダ"""
    folder = tmp_path / "docs"
    (folder / "sub").mkdir(parents=True)
    make_xlsx(folder / "sample.xlsx")
    make_docx(folder / "sample.docx")
    make_pptx(folder / "sub" / "sample.pptx")
    make_pdf(folder / "sample.pdf")
    (folder / "memo.txt").write_bytes("一行目\nバナナの話 banana\n\n四行目\n".encode("cp932"))
    (folder / "notes.md").write_text("# 見出し\n\n- バナナ\n- りんご <b>tag</b>\n", encoding="utf-8")
    (folder / "~$sample.xlsx").write_bytes(b"lock")  # Officeのロックファイル（対象外）
    (folder / "image.png").write_bytes(b"\x89PNG")
    return folder
