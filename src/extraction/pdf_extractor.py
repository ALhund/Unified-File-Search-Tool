"""PDF抽出モジュール（pypdfium2 / PDFium を使用）"""

from pathlib import Path

from src.common.logger import get_logger
from src.common.pdf_layout import PDFIUM_LOCK, open_document, page_blocks
from src.extraction.base import TextExtractor, ExtractedContent, ContentBlock


class PdfExtractor(TextExtractor):
    """PDF（.pdf）からテキストを抽出"""
    
    def __init__(self):
        self._logger = get_logger("extraction")
    
    @property
    def supported_extensions(self) -> set[str]:
        return {"pdf"}
    
    def extract(self, file_path: Path) -> ExtractedContent:
        """PDFファイルからコンテンツを抽出
        
        ページ内の段落を1単位とし、折り返しで分かれた行は連結する。
        これにより行をまたぐ語（特に日本語）も検索できる。
        """
        result = ExtractedContent(file_path=file_path)
        
        try:
            with PDFIUM_LOCK:
                document = open_document(file_path)
            try:
                with PDFIUM_LOCK:
                    result.total_pages = len(document)
                for page_index in range(result.total_pages):
                    # ページ単位でロックを取り直し、プレビュー描画を待たせすぎない
                    with PDFIUM_LOCK:
                        page = document[page_index]
                        try:
                            blocks = page_blocks(page)
                        finally:
                            page.close()
                    for block in blocks:
                        if block.text:
                            result.blocks.append(ContentBlock(text=block.text, page=page_index + 1))
            finally:
                with PDFIUM_LOCK:
                    document.close()
            
            self._logger.debug(
                "extract",
                f"Extracted {len(result.blocks)} blocks from PDF file",
                file_path=str(file_path),
                pages=result.total_pages,
            )
        
        except ValueError as e:
            result.error = str(e)
            self._logger.warning("skip", f"Cannot open PDF: {file_path}", file_path=str(file_path))
        
        except Exception as e:
            result.error = str(e) or type(e).__name__
            self._logger.exception("error", f"Failed to extract from PDF: {file_path}", e, file_path=str(file_path))
        
        return result
