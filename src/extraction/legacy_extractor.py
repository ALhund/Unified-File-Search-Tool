"""旧形式の Office（.xls / .doc / .ppt）からテキストを取り出す

- .xls … xlrd（BSD ライセンス）でセルを読む
- .doc … OLE 複合ファイルの WordDocument ストリームを読み、ピーステーブルから本文を復元する
- .ppt … PowerPoint Document ストリームのレコードをたどり、スライドごとの文字を集める

.doc / .ppt はバイナリ形式の仕様（[MS-DOC] / [MS-PPT]）に沿って必要な部分だけを読む。
パスワード付きのファイルは読めない。
"""

import struct
from pathlib import Path

from src.common.logger import get_logger
from src.extraction.base import ContentBlock, ExtractedContent, TextExtractor


def _column_letters(index: int) -> str:
    """0始まりの列番号 → 列名"""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


class XlsExtractor(TextExtractor):
    """Excel 97-2003（.xls）"""
    
    def __init__(self):
        self._logger = get_logger("extraction")
    
    @property
    def supported_extensions(self) -> set[str]:
        return {"xls"}
    
    def extract(self, file_path: Path) -> ExtractedContent:
        import xlrd
        
        result = ExtractedContent(file_path=file_path)
        try:
            book = xlrd.open_workbook(str(file_path), on_demand=True, formatting_info=False)
            try:
                result.total_sheets = book.nsheets
                for sheet_index in range(book.nsheets):
                    sheet = book.sheet_by_index(sheet_index)
                    for r in range(sheet.nrows):
                        for c in range(sheet.ncols):
                            cell = sheet.cell(r, c)
                            if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                                continue
                            value = cell.value
                            if cell.ctype == xlrd.XL_CELL_NUMBER and float(value).is_integer():
                                text = str(int(value))
                            elif cell.ctype == xlrd.XL_CELL_DATE:
                                try:
                                    text = xlrd.xldate.xldate_as_datetime(value, book.datemode).strftime("%Y/%m/%d")
                                except Exception:
                                    text = str(value)
                            elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                                text = "TRUE" if value else "FALSE"
                            elif cell.ctype == xlrd.XL_CELL_ERROR:
                                continue
                            else:
                                text = str(value).strip()
                            if text:
                                result.blocks.append(ContentBlock(
                                    text=text, sheet=sheet.name, cell=f"{_column_letters(c)}{r + 1}",
                                ))
                    book.unload_sheet(sheet_index)
            finally:
                book.release_resources()
        except Exception as e:
            result.error = _friendly_error(e, "xls")
            self._logger.warning("skip", f"Cannot read xls: {file_path}", file_path=str(file_path), exception_message=str(e))
        return result


def _friendly_error(error: Exception, kind: str) -> str:
    message = str(error) or type(error).__name__
    if "encrypt" in message.lower() or "password" in message.lower():
        return "パスワードで保護されたファイルです"
    if "not an ole2" in message.lower() or "unsupported format" in message.lower():
        return f"ファイルが破損しているか、有効な {kind} ファイルではありません"
    return message


# ---------------------------------------------------------------------------
# Word 97-2003（.doc）
# ---------------------------------------------------------------------------

# 本文中の特殊文字
_FIELD_BEGIN, _FIELD_SEPARATOR, _FIELD_END = "\x13", "\x14", "\x15"
_CELL_MARK = "\x07"


def _clean_doc_text(text: str) -> str:
    """フィールドコード（{ PAGE } など）の命令部分を除き、結果の表示文字だけ残す"""
    out: list[str] = []
    stack: list[bool] = []  # 各フィールドで「結果部分」に入ったか
    for ch in text:
        if ch == _FIELD_BEGIN:
            stack.append(False)
            continue
        if ch == _FIELD_SEPARATOR:
            if stack:
                stack[-1] = True
            continue
        if ch == _FIELD_END:
            if stack:
                stack.pop()
            continue
        if stack and not stack[-1]:
            continue  # フィールドの命令部分
        if ch in "\x01\x02\x03\x04\x05\x08\x0c\x1e\x1f":
            if ch == "\x0c":
                out.append("\r")  # 改ページ
            elif ch == "\x1e":
                out.append("-")  # 改行しないハイフン
            continue
        out.append("\n" if ch == "\x0b" else ch)
    return "".join(out)


def read_doc_text(path: Path) -> tuple[str, list[int]]:
    """(全文, 各部分の文字数)
    
    各部分: 本文, 脚注, ヘッダー/フッター, (予約), コメント, 文末脚注, テキストボックス, ヘッダー内のテキストボックス
    """
    import olefile
    
    with olefile.OleFileIO(str(path)) as ole:
        if not ole.exists("WordDocument"):
            raise ValueError("Word の文書ではありません")
        word = ole.openstream("WordDocument").read()
        if struct.unpack_from("<H", word, 0)[0] != 0xA5EC:
            raise ValueError("Word 97-2003 形式ではありません")
        flags = struct.unpack_from("<H", word, 0x0A)[0]
        if flags & 0x0100:
            raise ValueError("パスワードで保護されたファイルです")
        table_name = "1Table" if flags & 0x0200 else "0Table"
        if not ole.exists(table_name):
            raise ValueError("文書の構造が読み取れません")
        table = ole.openstream(table_name).read()
    
    lengths = list(struct.unpack_from("<8i", word, 0x4C))
    fc_clx, lcb_clx = struct.unpack_from("<II", word, 0x01A2)
    clx = table[fc_clx:fc_clx + lcb_clx]
    
    # Clx: 書式（Prc）の並びを飛ばし、ピーステーブル（Pcdt）を探す
    position = 0
    while position < len(clx) and clx[position] == 0x01:
        size = struct.unpack_from("<H", clx, position + 1)[0]
        position += 3 + size
    if position >= len(clx) or clx[position] != 0x02:
        raise ValueError("文書の構造が読み取れません")
    lcb = struct.unpack_from("<I", clx, position + 1)[0]
    plc = clx[position + 5:position + 5 + lcb]
    count = (lcb - 4) // 12
    cps = struct.unpack_from(f"<{count + 1}I", plc, 0)
    
    parts: list[str] = []
    for i in range(count):
        start_cp, end_cp = cps[i], cps[i + 1]
        length = end_cp - start_cp
        if length <= 0:
            continue
        fc = struct.unpack_from("<I", plc, (count + 1) * 4 + i * 8 + 2)[0]
        if fc & 0x40000000:
            offset = (fc & ~0x40000000) // 2
            parts.append(word[offset:offset + length].decode("cp1252", errors="replace"))
        else:
            parts.append(word[fc:fc + length * 2].decode("utf-16-le", errors="replace"))
    return "".join(parts), lengths


class DocExtractor(TextExtractor):
    """Word 97-2003（.doc）"""
    
    def __init__(self):
        self._logger = get_logger("extraction")
    
    @property
    def supported_extensions(self) -> set[str]:
        return {"doc"}
    
    def extract(self, file_path: Path) -> ExtractedContent:
        result = ExtractedContent(file_path=file_path)
        try:
            text, lengths = read_doc_text(file_path)
            kinds = [None, "note", "header", None, "note", "note", "shape", "shape"]
            number = 0
            position = 0
            seen: set[tuple] = set()
            for length, kind in zip(lengths, kinds):
                section_text = text[position:position + max(0, length)]
                position += max(0, length)
                for paragraph in _clean_doc_text(section_text).split("\r"):
                    # 表のセルは \x07 で区切られている
                    for piece in paragraph.split(_CELL_MARK):
                        piece = piece.strip()
                        if not piece:
                            continue
                        if kind is not None:
                            # ヘッダー・フッターは区切りごとに同じ内容が繰り返されるので1回だけ
                            if (kind, piece) in seen:
                                continue
                            seen.add((kind, piece))
                        number += 1
                        result.blocks.append(ContentBlock(text=piece, line=number, kind=kind))
        except Exception as e:
            result.error = _friendly_error(e, "doc")
            self._logger.warning("skip", f"Cannot read doc: {file_path}", file_path=str(file_path), exception_message=str(e))
        return result


# ---------------------------------------------------------------------------
# PowerPoint 97-2003（.ppt）
# ---------------------------------------------------------------------------

_RT_SLIDE = 0x03EE
_RT_NOTES = 0x03F0
_RT_MAIN_MASTER = 0x03F8
_RT_SLIDE_LIST_WITH_TEXT = 0x0FF0
_RT_SLIDE_PERSIST_ATOM = 0x03F3
_RT_TEXT_CHARS = 0x0FA0
_RT_TEXT_BYTES = 0x0FA8
_RT_NOTES_ATOM = 0x03F1
_RT_PERSIST_DIRECTORY = 0x1772


def _iter_records(data: bytes, start: int, end: int):
    """(種類, インスタンス, 中身の開始, 中身の終了, コンテナか) を順に返す"""
    position = start
    while position + 8 <= end:
        ver_inst, rec_type, length = struct.unpack_from("<HHI", data, position)
        body = position + 8
        stop = min(end, body + length)
        yield rec_type, ver_inst >> 4, body, stop, (ver_inst & 0x000F) == 0x000F
        position = body + length


class PptExtractor(TextExtractor):
    """PowerPoint 97-2003（.ppt）"""
    
    def __init__(self):
        self._logger = get_logger("extraction")
    
    @property
    def supported_extensions(self) -> set[str]:
        return {"ppt"}
    
    def extract(self, file_path: Path) -> ExtractedContent:
        import olefile
        
        result = ExtractedContent(file_path=file_path)
        try:
            with olefile.OleFileIO(str(file_path)) as ole:
                if not ole.exists("PowerPoint Document"):
                    raise ValueError("PowerPoint のファイルではありません")
                data = ole.openstream("PowerPoint Document").read()
            texts = self._collect(data)
            result.total_slides = max([slide for slide, _, _ in texts if slide], default=0) or None
            seen: set[tuple] = set()
            for slide, kind, text in texts:
                key = (slide, kind, text)
                if key in seen:
                    continue
                seen.add(key)
                result.blocks.append(ContentBlock(text=text, slide=slide or None, kind=kind))
        except Exception as e:
            result.error = _friendly_error(e, "ppt")
            self._logger.warning("skip", f"Cannot read ppt: {file_path}", file_path=str(file_path), exception_message=str(e))
        return result
    
    def _collect(self, data: bytes) -> list[tuple[int, str, str]]:
        """(スライド番号, 種類, 文字) の一覧
        
        スライドの順番は SlideListWithText の SlidePersistAtom の並び。各スライドの実体の位置は
        PersistDirectoryAtom（永続ID → ファイル内の位置）から求める。
        """
        # 1. 永続ID → 位置、スライドの並び、スライドID → スライド番号
        directory: dict[int, int] = {}
        slide_persist: list[int] = []
        slide_ids: dict[int, int] = {}
        
        def scan(start: int, end: int, in_list: bool) -> None:
            for rec_type, instance, body, stop, container in _iter_records(data, start, end):
                if rec_type == _RT_PERSIST_DIRECTORY:
                    position = body
                    while position + 4 <= stop:
                        header = struct.unpack_from("<I", data, position)[0]
                        persist_id, count = header & 0xFFFFF, header >> 20
                        position += 4
                        for i in range(count):
                            if position + 4 > stop:
                                break
                            directory[persist_id + i] = struct.unpack_from("<I", data, position)[0]
                            position += 4
                elif rec_type == _RT_SLIDE_LIST_WITH_TEXT:
                    scan(body, stop, instance == 0)
                elif rec_type == _RT_SLIDE_PERSIST_ATOM and in_list and stop - body >= 16:
                    persist_ref, _flags, _texts, slide_id = struct.unpack_from("<IIiI", data, body)
                    slide_persist.append(persist_ref)
                    slide_ids[slide_id] = len(slide_persist)
                elif container and rec_type not in (_RT_SLIDE, _RT_NOTES, _RT_MAIN_MASTER):
                    scan(body, stop, in_list)
        
        scan(0, len(data), False)
        slide_at = {directory[p]: number for number, p in enumerate(slide_persist, start=1) if p in directory}
        
        texts: list[tuple[int, str, str]] = []
        
        def add(slide: int, kind, raw: str) -> None:
            text = raw.replace("\r", "\n").replace("\x0b", "\n").strip()
            if text and text != "*":  # "*" はスライド番号などの差し込み欄
                texts.append((slide, kind, text))
        
        def text_of(rec_type: int, body: int, stop: int) -> str:
            raw = data[body:stop]
            return raw.decode("utf-16-le", errors="replace") if rec_type == _RT_TEXT_CHARS else raw.decode("latin-1")
        
        def collect(start: int, end: int, slide: int, kind) -> None:
            for rec_type, _instance, body, stop, container in _iter_records(data, start, end):
                if rec_type in (_RT_TEXT_CHARS, _RT_TEXT_BYTES):
                    add(slide, kind, text_of(rec_type, body, stop))
                elif container:
                    collect(body, stop, slide, kind)
        
        def walk(start: int, end: int) -> None:
            for rec_type, instance, body, stop, container in _iter_records(data, start, end):
                record_start = body - 8
                if rec_type == _RT_SLIDE:
                    number = slide_at.get(record_start)
                    if number:  # 番号が無いものはマスター（見本の文字なので除く）
                        collect(body, stop, number, None)
                elif rec_type == _RT_NOTES:
                    # NotesAtom の slideIdRef で、どのスライドのノートかが分かる（0 はノートのマスター）
                    for child, _i, child_body, child_stop, _c in _iter_records(data, body, stop):
                        if child == _RT_NOTES_ATOM and child_stop - child_body >= 4:
                            number = slide_ids.get(struct.unpack_from("<I", data, child_body)[0])
                            if number:
                                collect(body, stop, number, "note")
                            break
                elif rec_type == _RT_SLIDE_LIST_WITH_TEXT and instance == 0:
                    # プレースホルダー（タイトル・本文）の文字は SlideListWithText にある
                    current = 0
                    for child, _i, child_body, child_stop, _c in _iter_records(data, body, stop):
                        if child == _RT_SLIDE_PERSIST_ATOM:
                            current += 1
                        elif child in (_RT_TEXT_CHARS, _RT_TEXT_BYTES) and current:
                            add(current, None, text_of(child, child_body, child_stop))
                elif rec_type == _RT_MAIN_MASTER:
                    continue
                elif container:
                    walk(body, stop)
        
        walk(0, len(data))
        return texts
