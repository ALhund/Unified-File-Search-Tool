"""Extractorファクトリ"""

from pathlib import Path
from typing import Optional

from src.extraction.base import TextExtractor
from src.extraction.text_extractor import PlainTextExtractor
from src.extraction.office_extractor import (
    WordExtractor,
    ExcelExtractor,
    PowerPointExtractor,
)
from src.extraction.pdf_extractor import PdfExtractor


# 登録されたExtractor一覧
_extractors: list[TextExtractor] = [
    PlainTextExtractor(),
    WordExtractor(),
    ExcelExtractor(),
    PowerPointExtractor(),
    PdfExtractor(),
]


def get_extractor(file_path: Path) -> Optional[TextExtractor]:
    """ファイルに対応するExtractorを取得
    
    Args:
        file_path: 対象ファイルのパス
    
    Returns:
        対応するExtractor、見つからない場合はNone
    """
    for extractor in _extractors:
        if extractor.can_extract(file_path):
            return extractor
    return None


def get_extractor_by_extension(extension: str) -> Optional[TextExtractor]:
    """拡張子からExtractorを取得
    
    Args:
        extension: 拡張子（ドットなし小文字）
    
    Returns:
        対応するExtractor、見つからない場合はNone
    """
    ext = extension.lower().lstrip(".")
    for extractor in _extractors:
        if ext in extractor.supported_extensions:
            return extractor
    return None


def get_supported_extensions() -> set[str]:
    """サポートされている全拡張子を取得"""
    extensions = set()
    for extractor in _extractors:
        extensions.update(extractor.supported_extensions)
    return extensions
