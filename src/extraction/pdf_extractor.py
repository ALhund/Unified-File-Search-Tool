"""PDF テキスト抽出モジュール。

PyMuPDF (fitz) を使用して PDF ファイルからテキストを抽出する。
段落ごとに :class:`ContentBlock` を生成し、ページ番号を付与する。
"""

from pathlib import Path

from src.common.logger import get_logger
from src.extraction.base import ContentBlock, ExtractedContent, TextExtractor


class PdfExtractor(TextExtractor):
    """PDF（.pdf）からテキストを抽出する Extractor。

    各ページのテキストを ``\\n\\n`` で段落に分割し、
    段落内の改行はスペースに置換して :class:`ContentBlock` を生成する。
    """

    def __init__(self) -> None:
        self._logger = get_logger("extraction")

    @property
    def supported_extensions(self) -> set[str]:
        """サポートする拡張子: ``{"pdf"}``。"""
        return {"pdf"}

    def extract(self, file_path: Path) -> ExtractedContent:
        """PDF ファイルからコンテンツを抽出する。

        PyMuPDF (``fitz``) でファイルを開き、全ページを走査する。
        各ページのテキストは二重改行で段落に分割し、
        段落内の改行はスペースに変換してブロックに追加する。

        Args:
            file_path: 抽出対象の .pdf ファイルパス。

        Returns:
            抽出されたコンテンツ。エラー時は ``error`` が設定される。
        """
        import fitz  # PyMuPDF

        result = ExtractedContent(file_path=file_path)

        try:
            doc = fitz.open(file_path)
            result.total_pages = len(doc)

            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text("text")

                # 二重改行で段落に分割し、段落内の改行はスペースに置換
                for para in text.split("\n\n"):
                    para = para.strip()
                    if para:
                        result.blocks.append(ContentBlock(
                            text=para.replace("\n", " "),
                            page=page_num + 1,
                        ))

            doc.close()

            self._logger.debug(
                "extract",
                f"Extracted {len(result.blocks)} blocks from PDF file",
                file_path=str(file_path),
                pages=result.total_pages,
            )

        except fitz.FileDataError as exc:
            result.error = (
                "ファイルが破損しているか、有効な PDF ファイルではありません"
            )
            self._logger.warning(
                "skip",
                f"Invalid PDF file: {file_path}",
                file_path=str(file_path),
                exception_message=str(exc),
            )

        except Exception as exc:
            result.error = str(exc)
            self._logger.exception(
                "error",
                f"Failed to extract from PDF: {file_path}",
                exc,
                file_path=str(file_path),
            )

        return result
