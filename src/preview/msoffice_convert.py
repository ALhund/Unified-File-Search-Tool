"""Microsoft Office（COM）でPDFへ変換する子プロセス用スクリプト（Windows専用）

使い方: python -m src.preview.msoffice_convert <入力ファイル> <出力PDF>

- 既に開いているOfficeとは別のインスタンスを起動し、終了時に閉じる
- マクロは無効化し、ファイルは読み取り専用で開いて保存しない
- Excelは全ての列を1ページの幅に収める（列の途中でページが分かれない）
"""

import sys
from pathlib import Path

MSO_AUTOMATION_SECURITY_FORCE_DISABLE = 3
XL_TYPE_PDF = 0
WD_EXPORT_FORMAT_PDF = 17
PP_SAVE_AS_PDF = 32
XL_SHEET_VISIBLE = -1


def _disable_macros(app) -> None:
    try:
        app.AutomationSecurity = MSO_AUTOMATION_SECURITY_FORCE_DISABLE
    except Exception:
        pass


def convert_excel(src: str, dst: str) -> None:
    import win32com.client
    
    app = win32com.client.DispatchEx("Excel.Application")
    try:
        app.Visible = False
        app.DisplayAlerts = False
        app.ScreenUpdating = False
        _disable_macros(app)
        book = app.Workbooks.Open(src, UpdateLinks=0, ReadOnly=True, AddToMru=False)
        try:
            for sheet in book.Worksheets:
                if sheet.Visible != XL_SHEET_VISIBLE:
                    continue
                try:
                    setup = sheet.PageSetup
                    setup.PrintArea = ""  # 印刷範囲の指定に関係なくシート全体を出す
                    setup.Zoom = False
                    setup.FitToPagesWide = 1
                    setup.FitToPagesTall = False  # 縦は必要なだけページを使う
                except Exception:
                    pass  # 保護されたシート等は既定のページ設定のまま出力する
            book.ExportAsFixedFormat(XL_TYPE_PDF, dst)
        finally:
            book.Close(SaveChanges=False)
    finally:
        app.Quit()


def convert_word(src: str, dst: str) -> None:
    import win32com.client
    
    app = win32com.client.DispatchEx("Word.Application")
    try:
        app.Visible = False
        app.DisplayAlerts = 0
        _disable_macros(app)
        doc = app.Documents.Open(
            src, ConfirmConversions=False, ReadOnly=True, AddToRecentFiles=False, Visible=False
        )
        try:
            doc.ExportAsFixedFormat(dst, WD_EXPORT_FORMAT_PDF)
        finally:
            doc.Close(SaveChanges=0)
    finally:
        app.Quit()


def convert_powerpoint(src: str, dst: str) -> None:
    import win32com.client
    
    app = win32com.client.DispatchEx("PowerPoint.Application")
    try:
        _disable_macros(app)
        deck = app.Presentations.Open(src, ReadOnly=True, Untitled=False, WithWindow=False)
        try:
            deck.SaveAs(dst, PP_SAVE_AS_PDF)
        finally:
            deck.Close()
    finally:
        app.Quit()


CONVERTERS = {
    ".xlsx": convert_excel,
    ".xlsm": convert_excel,
    ".docx": convert_word,
    ".pptx": convert_powerpoint,
}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    
    src = str(Path(argv[1]).resolve())
    dst = str(Path(argv[2]).resolve())
    converter = CONVERTERS.get(Path(src).suffix.lower())
    if converter is None:
        print(f"unsupported file type: {src}", file=sys.stderr)
        return 2
    
    import pythoncom
    
    pythoncom.CoInitialize()
    try:
        converter(src, dst)
    except Exception as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        pythoncom.CoUninitialize()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
