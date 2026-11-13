"""検索結果を Excel（.xlsx）に書き出す

シート:
  ファイル一覧 … 1行1ファイル（ファイル名からそのファイルを開けるリンク）
  ヒット箇所   … 1行1ヒット（検索語の部分を赤の太字で強調）
  検索条件     … 検索語・方法・フォルダ・日時など
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from src.search import SearchOptions, SearchResult

MAX_HIT_ROWS = 200_000  # Excel の行数上限より十分少なくする

HEADER_FILL = "1F4E79"
HEADER_FONT = "FFFFFF"
STRIPE_FILL = "F3F6FA"
MATCH_COLOR = "C00000"

MODE_NAMES = {"and": "すべての語を含む", "or": "いずれかの語を含む", "phrase": "入力どおりの語句"}


def _illegal_free(text: str) -> str:
    """Excel のセルに入れられない制御文字を取り除く"""
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    return ILLEGAL_CHARACTERS_RE.sub("", text or "")


def _relative_folder(path: Path, root: Optional[Path]) -> str:
    if root is not None:
        try:
            relative = path.parent.relative_to(root)
            return "（検索フォルダ直下）" if str(relative) == "." else str(relative)
        except ValueError:
            pass
    return str(path.parent)


def export_results(
    destination: Path,
    results: list[SearchResult],
    options: Optional[SearchOptions],
    root: Optional[Path],
    extra_conditions: Optional[dict[str, str]] = None,
) -> tuple[int, int]:
    """書き出す（戻り値: (ファイル数, ヒット行数)）"""
    from openpyxl import Workbook
    from openpyxl.cell.rich_text import CellRichText, TextBlock
    from openpyxl.cell.text import InlineFont
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    
    workbook = Workbook()
    header_font = Font(bold=True, color=HEADER_FONT)
    header_fill = PatternFill("solid", fgColor=HEADER_FILL)
    stripe = PatternFill("solid", fgColor=STRIPE_FILL)
    thin = Side(style="thin", color="D0D7E2")
    border = Border(bottom=thin)
    link_font = Font(color="0563C1", underline="single")
    wrap = Alignment(wrap_text=True, vertical="top")
    top = Alignment(vertical="top")
    
    def setup_sheet(sheet, headers: list[tuple[str, int]]) -> None:
        for column, (title, width) in enumerate(headers, start=1):
            cell = sheet.cell(row=1, column=column, value=title)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(vertical="center")
            sheet.column_dimensions[get_column_letter(column)].width = width
        sheet.row_dimensions[1].height = 22
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}1"
    
    def finish_rows(sheet, row: int, columns: int) -> None:
        for column in range(1, columns + 1):
            cell = sheet.cell(row=row, column=column)
            cell.border = border
            if row % 2 == 1:
                cell.fill = stripe
    
    def snippet(before: str, matched: str, after: str):
        before, matched, after = (_illegal_free(" ".join(t.split())) for t in (before, matched, after))
        parts = []
        if before:
            parts.append(before)
        parts.append(TextBlock(InlineFont(b=True, color=MATCH_COLOR), matched or " "))
        if after:
            parts.append(after)
        return CellRichText(*parts)
    
    ok_results = [r for r in results if not r.error]
    error_results = [r for r in results if r.error]
    
    # --- ファイル一覧 ---
    files_sheet = workbook.active
    files_sheet.title = "ファイル一覧"
    setup_sheet(files_sheet, [
        ("No.", 6), ("ファイル名", 34), ("件数", 8), ("最初のヒット位置", 24), ("最初のヒット（抜粋）", 60),
        ("フォルダ", 36), ("種類", 7), ("更新日時", 17), ("サイズ(KB)", 11), ("フルパス", 60),
    ])
    row = 2
    for number, result in enumerate(ok_results + error_results, start=1):
        info = result.file_info
        files_sheet.cell(row=row, column=1, value=number).alignment = top
        name = files_sheet.cell(row=row, column=2, value=_illegal_free(info.name))
        name.hyperlink = info.path.resolve().as_uri()
        name.font = link_font
        name.alignment = top
        if result.error:
            files_sheet.cell(row=row, column=3, value="エラー").font = Font(color=MATCH_COLOR)
            files_sheet.cell(row=row, column=5, value=_illegal_free(f"読み込めませんでした: {result.error}")).alignment = wrap
        else:
            count = files_sheet.cell(row=row, column=3, value=result.match_count)
            if result.truncated:
                count.value = f"{result.match_count}+"
            count.alignment = Alignment(horizontal="right", vertical="top")
            first = result.matches[0]
            files_sheet.cell(row=row, column=4, value=_illegal_free(first.location)).alignment = top
            files_sheet.cell(row=row, column=5, value=snippet(first.before, first.matched_text, first.after)).alignment = wrap
        files_sheet.cell(row=row, column=6, value=_illegal_free(_relative_folder(info.path, root))).alignment = top
        files_sheet.cell(row=row, column=7, value=info.extension).alignment = top
        modified = files_sheet.cell(row=row, column=8, value=info.modified_time.replace(microsecond=0))
        modified.number_format = "yyyy/mm/dd hh:mm"
        modified.alignment = top
        size = files_sheet.cell(row=row, column=9, value=round(info.size / 1024, 1))
        size.number_format = "#,##0.0"
        size.alignment = top
        files_sheet.cell(row=row, column=10, value=_illegal_free(str(info.path))).alignment = top
        finish_rows(files_sheet, row, 10)
        row += 1
    
    # --- ヒット箇所 ---
    hits_sheet = workbook.create_sheet("ヒット箇所")
    setup_sheet(hits_sheet, [
        ("No.", 7), ("ファイル名", 30), ("位置", 26), ("ヒット（前後を含む）", 80), ("一致した文字", 18), ("フルパス", 60),
    ])
    row = 2
    hit_rows = 0
    for result in ok_results:
        info = result.file_info
        uri = info.path.resolve().as_uri()
        for match in result.matches:
            if hit_rows >= MAX_HIT_ROWS:
                break
            hit_rows += 1
            hits_sheet.cell(row=row, column=1, value=hit_rows).alignment = top
            name = hits_sheet.cell(row=row, column=2, value=_illegal_free(info.name))
            name.hyperlink = uri
            name.font = link_font
            name.alignment = top
            hits_sheet.cell(row=row, column=3, value=_illegal_free(match.location)).alignment = top
            hits_sheet.cell(row=row, column=4, value=snippet(match.before, match.matched_text, match.after)).alignment = wrap
            hits_sheet.cell(row=row, column=5, value=_illegal_free(match.matched_text)).alignment = top
            hits_sheet.cell(row=row, column=6, value=_illegal_free(str(info.path))).alignment = top
            finish_rows(hits_sheet, row, 6)
            row += 1
    
    # --- 検索条件 ---
    conditions = workbook.create_sheet("検索条件")
    conditions.column_dimensions["A"].width = 22
    conditions.column_dimensions["B"].width = 80
    items: list[tuple[str, str]] = [("書き出した日時", datetime.now().strftime("%Y/%m/%d %H:%M"))]
    if options is not None:
        items += [
            ("検索語", options.query),
            ("検索方法", "正規表現" if options.use_regex else MODE_NAMES.get(options.term_mode, options.term_mode)),
            ("大文字/小文字", "区別する" if options.case_sensitive else "区別しない"),
            ("全角/半角", "区別しない" if options.ignore_width else "区別する"),
            ("完全一致", "する" if options.match_whole else "しない"),
            ("除外語", "、".join(options.exclude_words) or "なし"),
        ]
    if root is not None:
        items.append(("検索フォルダ", str(root)))
    items += list((extra_conditions or {}).items())
    items += [
        ("ヒットしたファイル", f"{len(ok_results):,} 件"),
        ("ヒット箇所", f"{sum(r.match_count for r in ok_results):,} 件"
                      + ("（多いため一部のみ書き出し）" if hit_rows >= MAX_HIT_ROWS else "")),
        ("読み込めなかったファイル", f"{len(error_results):,} 件"),
    ]
    for r, (key, value) in enumerate(items, start=1):
        conditions.cell(row=r, column=1, value=key).font = Font(bold=True)
        conditions.cell(row=r, column=2, value=_illegal_free(value))
    
    workbook.properties.creator = "Unified File Search"
    workbook.properties.title = "検索結果"
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(destination)
    return len(results), hit_rows
