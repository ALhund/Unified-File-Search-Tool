"""PDF抽出モジュール"""

from pathlib import Path

from src.common.logger import get_logger
from src.common.textnorm import join_wrapped_lines
from src.common.utils import FITZ_LOCK
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
        
        ページ内のテキストブロック（段落相当）を1単位とし、折り返しで分かれた行は
        連結する。これにより行をまたぐ語（特に日本語）も検索できる。
        """
        import pymupdf as fitz
        
        result = ExtractedContent(file_path=file_path)
        
        try:
            with FITZ_LOCK:
                doc = fitz.open(str(file_path))
            try:
                with FITZ_LOCK:
                    if doc.needs_pass:
                        result.error = "パスワードで保護されたPDFです"
                        return result
                    result.total_pages = len(doc)
                
                for page_num in range(result.total_pages):
                    # ページ単位でロックを取り直し、プレビュー描画を待たせすぎない
                    with FITZ_LOCK:
                        blocks = doc[page_num].get_text("blocks", sort=True)
                    
                    for block in blocks:
                        if block[6] != 0:  # 画像ブロック
                            continue
                        text = join_wrapped_lines(
                            [line.strip() for line in block[4].split("\n")]
                        )
                        if text:
                            result.blocks.append(ContentBlock(text=text, page=page_num + 1))
            finally:
                with FITZ_LOCK:
                    doc.close()
            
            self._logger.debug(
                "extract",
                f"Extracted {len(result.blocks)} blocks from PDF file",
                file_path=str(file_path),
                pages=result.total_pages,
            )
        
        except fitz.FileDataError:
            result.error = "ファイルが破損しているか、有効なPDFファイルではありません"
            self._logger.warning("skip", f"Invalid PDF file: {file_path}", file_path=str(file_path))
        
        except Exception as e:
            result.error = str(e) or type(e).__name__
            self._logger.exception("error", f"Failed to extract from PDF: {file_path}", e, file_path=str(file_path))
        
        return result
