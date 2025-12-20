"""PDF抽出モジュール"""

from pathlib import Path

from src.common.logger import get_logger
from src.extraction.base import TextExtractor, ExtractedContent, ContentBlock


class PdfExtractor(TextExtractor):
    """PDF（.pdf）からテキストを抽出"""
    
    def __init__(self):
        self._logger = get_logger("extraction")
    
    @property
    def supported_extensions(self) -> set[str]:
        return {"pdf"}
    
    def extract(self, file_path: Path) -> ExtractedContent:
        """PDFファイルからコンテンツを抽出"""
        import fitz  # PyMuPDF
        
        result = ExtractedContent(file_path=file_path)
        
        try:
            doc = fitz.open(file_path)
            result.total_pages = len(doc)
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text("text")
                
                # テキストを段落（連続する改行で分割）に分ける
                paragraphs = text.split("\n\n")
                for para in paragraphs:
                    para = para.strip()
                    if para:
                        # 段落内の改行は空白に置換
                        para = para.replace("\n", " ")
                        result.blocks.append(ContentBlock(
                            text=para,
                            page=page_num + 1,  # 1始まり
                        ))
            
            doc.close()
            
            self._logger.debug(
                "extract",
                f"Extracted {len(result.blocks)} blocks from PDF file",
                file_path=str(file_path),
                pages=result.total_pages,
            )
        
        except fitz.FileDataError as e:
            result.error = "ファイルが破損しているか、有効なPDFファイルではありません"
            self._logger.warning("skip", f"Invalid PDF file: {file_path}", file_path=str(file_path))
        
        except Exception as e:
            result.error = str(e)
            self._logger.exception("error", f"Failed to extract from PDF: {file_path}", e, file_path=str(file_path))
        
        return result
