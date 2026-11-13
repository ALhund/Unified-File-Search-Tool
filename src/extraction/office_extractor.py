"""Office形式抽出モジュール（docx, xlsx, pptx）"""

from pathlib import Path

from src.common.logger import get_logger
from src.extraction.base import TextExtractor, ExtractedContent, ContentBlock


class WordExtractor(TextExtractor):
    """Word（.docx）からテキストを抽出"""
    
    def __init__(self):
        self._logger = get_logger("extraction")
    
    @property
    def supported_extensions(self) -> set[str]:
        return {"docx"}
    
    def extract(self, file_path: Path) -> ExtractedContent:
        """Wordファイルからコンテンツを抽出（本文は文書の並び順どおり）"""
        from docx import Document
        from docx.opc.exceptions import PackageNotFoundError
        from docx.table import Table
        from docx.text.paragraph import Paragraph
        
        result = ExtractedContent(file_path=file_path)
        
        try:
            doc = Document(str(file_path))
            counter = {"line": 0, "table": 0}
            
            def add(text: str, **kwargs) -> None:
                text = text.strip()
                if text:
                    counter["line"] += 1
                    result.blocks.append(ContentBlock(text=text, line=counter["line"], **kwargs))
            
            def add_paragraph(para: Paragraph, **kwargs) -> None:
                kind = kwargs.pop("kind", None)
                if kind is None and _is_heading(para):
                    kind = "heading"
                add(para.text, kind=kind, **kwargs)
                # テキストボックス（段落にアンカーされた図形）の中身
                for text in _textbox_texts(para):
                    add(text, kind="shape")
            
            def add_table(table: Table) -> None:
                table_index = counter["table"]
                counter["table"] += 1
                # 結合セルは同じセルが繰り返し返るので1回だけ扱う。
                # （id() はオブジェクト解放後に再利用されるため、要素そのものを保持して比較する）
                seen: list = []
                for r, row in enumerate(table.rows):
                    for c, cell in enumerate(row.cells):
                        if any(cell._tc is element for element in seen):
                            continue
                        seen.append(cell._tc)
                        add(cell.text, table=(table_index, r, c))
                        for para in cell.paragraphs:
                            for text in _textbox_texts(para):
                                add(text, kind="shape")
            
            for section in doc.sections:
                if not section.header.is_linked_to_previous:
                    for para in section.header.paragraphs:
                        add_paragraph(para, kind="header")
            
            for item in doc.iter_inner_content():
                if isinstance(item, Paragraph):
                    add_paragraph(item)
                elif isinstance(item, Table):
                    add_table(item)
            
            for section in doc.sections:
                if not section.footer.is_linked_to_previous:
                    for para in section.footer.paragraphs:
                        add_paragraph(para, kind="footer")
            
            self._logger.debug(
                "extract",
                f"Extracted {len(result.blocks)} blocks from Word file",
                file_path=str(file_path),
            )
        
        except PackageNotFoundError:
            result.error = "ファイルが破損しているか、有効なdocxファイルではありません"
            self._logger.warning("skip", f"Invalid docx file: {file_path}", file_path=str(file_path))
        
        except Exception as e:
            result.error = str(e) or type(e).__name__
            self._logger.exception("error", f"Failed to extract from Word: {file_path}", e, file_path=str(file_path))
        
        return result


def _is_heading(para) -> bool:
    try:
        name = (para.style.name or "").lower()
    except Exception:
        return False
    return name.startswith(("heading", "title", "見出し", "表題"))


def _textbox_texts(para) -> list[str]:
    """段落内のテキストボックスの文字列（互換用の重複定義は1つにまとめる）"""
    from docx.oxml.ns import qn
    
    texts: list[str] = []
    for content in para._p.iter(qn("w:txbxContent")):
        lines = []
        for p in content.iter(qn("w:p")):
            line = "".join(t.text or "" for t in p.iter(qn("w:t")))
            if line.strip():
                lines.append(line)
        text = "\n".join(lines)
        if text and text not in texts:
            texts.append(text)
    return texts


class ExcelExtractor(TextExtractor):
    """Excel（.xlsx）からテキストを抽出"""
    
    def __init__(self):
        self._logger = get_logger("extraction")
    
    @property
    def supported_extensions(self) -> set[str]:
        return {"xlsx", "xlsm"}
    
    def extract(self, file_path: Path) -> ExtractedContent:
        """Excelファイルからコンテンツを抽出（セル + 図形・グラフ内の文字列）"""
        import zipfile
        from openpyxl import load_workbook
        from openpyxl.utils.exceptions import InvalidFileException
        from src.extraction.ooxml_drawing import extract_drawing_texts
        
        result = ExtractedContent(file_path=file_path)
        
        try:
            wb = load_workbook(str(file_path), read_only=True, data_only=True)
            try:
                result.total_sheets = len(wb.sheetnames)
                
                for sheet_name in wb.sheetnames:
                    sheet = wb[sheet_name]
                    if not hasattr(sheet, "iter_rows"):
                        continue  # グラフシート
                    
                    for row in sheet.iter_rows():
                        for cell in row:
                            value = cell.value
                            if value is None:
                                continue
                            text = _cell_text(value)
                            if text:
                                result.blocks.append(ContentBlock(
                                    text=text,
                                    sheet=sheet_name,
                                    cell=cell.coordinate,
                                ))
            finally:
                wb.close()
            
            # 図形・テキストボックス・グラフタイトル
            try:
                for drawing in extract_drawing_texts(file_path):
                    result.blocks.append(ContentBlock(
                        text=drawing.text,
                        sheet=drawing.sheet,
                        cell=drawing.cell,
                        kind=drawing.kind,
                    ))
            except Exception as e:
                self._logger.warning(
                    "drawing",
                    f"Failed to read drawings: {file_path}",
                    file_path=str(file_path),
                    exception_message=str(e),
                )
            
            self._logger.debug(
                "extract",
                f"Extracted {len(result.blocks)} blocks from Excel file",
                file_path=str(file_path),
                sheets=result.total_sheets,
            )
        
        except (InvalidFileException, zipfile.BadZipFile):
            result.error = "ファイルが破損しているか、有効なxlsxファイルではありません"
            self._logger.warning("skip", f"Invalid xlsx file: {file_path}", file_path=str(file_path))
        
        except Exception as e:
            result.error = str(e) or type(e).__name__
            self._logger.exception("error", f"Failed to extract from Excel: {file_path}", e, file_path=str(file_path))
        
        return result


def _cell_text(value) -> str:
    """セル値を検索用の文字列にする（1234.0 のような表記を避ける）"""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _chart_text(chart) -> str:
    """グラフのタイトル・系列名・項目名"""
    lines: list[str] = []
    try:
        if chart.has_title and chart.chart_title.has_text_frame:
            lines.append(chart.chart_title.text_frame.text.strip())
    except Exception:
        pass
    try:
        for plot in chart.plots:
            lines.extend(str(c) for c in plot.categories if str(c).strip())
            lines.extend(series.name for series in plot.series if series.name)
    except Exception:
        pass
    unique: list[str] = []
    for line in lines:
        if line and line not in unique:
            unique.append(line)
    return "\n".join(unique)


class PowerPointExtractor(TextExtractor):
    """PowerPoint（.pptx）からテキストを抽出"""
    
    def __init__(self):
        self._logger = get_logger("extraction")
    
    @property
    def supported_extensions(self) -> set[str]:
        return {"pptx"}
    
    def extract(self, file_path: Path) -> ExtractedContent:
        """PowerPointファイルからコンテンツを抽出"""
        from pptx import Presentation
        from pptx.exc import PackageNotFoundError
        
        result = ExtractedContent(file_path=file_path)
        
        try:
            prs = Presentation(str(file_path))
            result.total_slides = len(prs.slides)
            
            for slide_num, slide in enumerate(prs.slides, start=1):
                table_counter = [0]
                self._extract_shapes(slide.shapes, slide_num, result, table_counter)
                
                if slide.has_notes_slide:
                    notes = slide.notes_slide.notes_text_frame
                    text = notes.text.strip() if notes is not None else ""
                    if text:
                        result.blocks.append(ContentBlock(text=text, slide=slide_num, kind="note"))
            
            self._logger.debug(
                "extract",
                f"Extracted {len(result.blocks)} blocks from PowerPoint file",
                file_path=str(file_path),
                slides=result.total_slides,
            )
        
        except PackageNotFoundError:
            result.error = "ファイルが破損しているか、有効なpptxファイルではありません"
            self._logger.warning("skip", f"Invalid pptx file: {file_path}", file_path=str(file_path))
        
        except Exception as e:
            result.error = str(e) or type(e).__name__
            self._logger.exception("error", f"Failed to extract from PowerPoint: {file_path}", e, file_path=str(file_path))
        
        return result
    
    def _extract_shapes(self, shapes, slide_num: int, result: ExtractedContent, table_counter: list[int]) -> None:
        """図形を再帰的にたどる（グループ化された図形の中も対象）"""
        from pptx.enum.shapes import MSO_SHAPE_TYPE
        
        for shape in shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                self._extract_shapes(shape.shapes, slide_num, result, table_counter)
                continue
            
            if getattr(shape, "has_table", False) and shape.has_table:
                table_index = table_counter[0]
                table_counter[0] += 1
                for r, row in enumerate(shape.table.rows):
                    for c, cell in enumerate(row.cells):
                        text = cell.text.strip()
                        if text:
                            result.blocks.append(ContentBlock(
                                text=text,
                                slide=slide_num,
                                table=(table_index, r, c),
                            ))
                continue
            
            if getattr(shape, "has_chart", False) and shape.has_chart:
                text = _chart_text(shape.chart)
                if text:
                    result.blocks.append(ContentBlock(text=text, slide=slide_num, kind="chart"))
                continue
            
            if shape.has_text_frame:
                text = shape.text_frame.text.strip()
                if text:
                    result.blocks.append(ContentBlock(text=text, slide=slide_num))
