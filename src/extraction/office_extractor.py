"""Office形式抽出モジュール（docx, xlsx, pptx）"""

from pathlib import Path
from typing import Optional

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
        """Wordファイルからコンテンツを抽出"""
        from docx import Document
        from docx.opc.exceptions import PackageNotFoundError
        
        result = ExtractedContent(file_path=file_path)
        
        try:
            doc = Document(file_path)
            
            # 段落を抽出（ページ番号の正確な取得は困難なため、段落番号で代用）
            para_num = 0
            for para in doc.paragraphs:
                text = para.text.strip()
                if text:
                    para_num += 1
                    result.blocks.append(ContentBlock(
                        text=text,
                        page=1,  # Wordのページ番号は正確に取れないので暫定
                        line=para_num,
                    ))
            
            # テーブル内のテキストも抽出
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        text = cell.text.strip()
                        if text:
                            para_num += 1
                            result.blocks.append(ContentBlock(
                                text=text,
                                page=1,
                                line=para_num,
                            ))
            
            result.total_pages = 1  # 正確なページ数取得は困難
            
            self._logger.debug(
                "extract",
                f"Extracted {len(result.blocks)} blocks from Word file",
                file_path=str(file_path),
            )
        
        except PackageNotFoundError as e:
            result.error = "ファイルが破損しているか、有効なdocxファイルではありません"
            self._logger.warning("skip", f"Invalid docx file: {file_path}", file_path=str(file_path))
        
        except Exception as e:
            result.error = str(e)
            self._logger.exception("error", f"Failed to extract from Word: {file_path}", e, file_path=str(file_path))
        
        return result


class ExcelExtractor(TextExtractor):
    """Excel（.xlsx）からテキストを抽出"""
    
    def __init__(self):
        self._logger = get_logger("extraction")
    
    @property
    def supported_extensions(self) -> set[str]:
        return {"xlsx"}
    
    def extract(self, file_path: Path) -> ExtractedContent:
        """Excelファイルからコンテンツを抽出"""
        from openpyxl import load_workbook
        from openpyxl.utils.exceptions import InvalidFileException
        
        result = ExtractedContent(file_path=file_path)
        
        try:
            wb = load_workbook(file_path, read_only=True, data_only=True)
            result.total_sheets = len(wb.sheetnames)
            
            for sheet_name in wb.sheetnames:
                sheet = wb[sheet_name]
                
                for row_idx, row in enumerate(sheet.iter_rows(), start=1):
                    for cell in row:
                        if cell.value is not None:
                            text = str(cell.value).strip()
                            if text:
                                result.blocks.append(ContentBlock(
                                    text=text,
                                    sheet=sheet_name,
                                    cell=cell.coordinate,
                                ))
            
            wb.close()
            
            self._logger.debug(
                "extract",
                f"Extracted {len(result.blocks)} blocks from Excel file",
                file_path=str(file_path),
                sheets=result.total_sheets,
            )
        
        except InvalidFileException as e:
            result.error = "ファイルが破損しているか、有効なxlsxファイルではありません"
            self._logger.warning("skip", f"Invalid xlsx file: {file_path}", file_path=str(file_path))
        
        except Exception as e:
            result.error = str(e)
            self._logger.exception("error", f"Failed to extract from Excel: {file_path}", e, file_path=str(file_path))
        
        return result


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
            prs = Presentation(file_path)
            result.total_slides = len(prs.slides)
            
            for slide_num, slide in enumerate(prs.slides, start=1):
                for shape in slide.shapes:
                    if hasattr(shape, "text"):
                        text = shape.text.strip()
                        if text:
                            result.blocks.append(ContentBlock(
                                text=text,
                                slide=slide_num,
                            ))
                    
                    # テーブル内のテキスト
                    if shape.has_table:
                        table = shape.table
                        for row in table.rows:
                            for cell in row.cells:
                                text = cell.text.strip()
                                if text:
                                    result.blocks.append(ContentBlock(
                                        text=text,
                                        slide=slide_num,
                                    ))
            
            self._logger.debug(
                "extract",
                f"Extracted {len(result.blocks)} blocks from PowerPoint file",
                file_path=str(file_path),
                slides=result.total_slides,
            )
        
        except PackageNotFoundError as e:
            result.error = "ファイルが破損しているか、有効なpptxファイルではありません"
            self._logger.warning("skip", f"Invalid pptx file: {file_path}", file_path=str(file_path))
        
        except Exception as e:
            result.error = str(e)
            self._logger.exception("error", f"Failed to extract from PowerPoint: {file_path}", e, file_path=str(file_path))
        
        return result
