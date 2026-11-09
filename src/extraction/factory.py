"""Extractorファクトリ"""

from pathlib import Path
from typing import Optional

from src.extraction.base import TextExtractor, ExtractedContent
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


_by_extension: dict[str, TextExtractor] = {
    ext: extractor for extractor in _extractors for ext in extractor.supported_extensions
}


def get_extractor(file_path: Path) -> Optional[TextExtractor]:
    """ファイルに対応するExtractorを取得
    
    Args:
        file_path: 対象ファイルのパス
    
    Returns:
        対応するExtractor、見つからない場合はNone
    """
    return get_extractor_by_extension(Path(file_path).suffix)


def extract_file(file_path: str) -> ExtractedContent:
    """ファイルからテキストを抽出する（並列実行用にプロセス間で受け渡せる形）"""
    path = Path(file_path)
    extractor = get_extractor(path)
    if extractor is None:
        return ExtractedContent(file_path=path, error=f"サポートされていない形式: {path.suffix}")
    return extractor.extract(path)


def get_extractor_by_extension(extension: str) -> Optional[TextExtractor]:
    """拡張子からExtractorを取得
    
    Args:
        extension: 拡張子（ドットなし小文字）
    
    Returns:
        対応するExtractor、見つからない場合はNone
    """
    return _by_extension.get(extension.lower().lstrip("."))


def get_supported_extensions() -> set[str]:
    """サポートされている全拡張子を取得"""
    return set(_by_extension)
