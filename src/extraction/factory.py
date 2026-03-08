"""Extractor ファクトリモジュール。

ファイルパスまたは拡張子から適切な :class:`TextExtractor` を返すディスパッチ関数を提供する。

使用例::

    extractor = get_extractor(Path("report.xlsx"))
    if extractor:
        content = extractor.extract(Path("report.xlsx"))
"""

from pathlib import Path

from src.extraction.base import TextExtractor
from src.extraction.office_extractor import (
    ExcelExtractor,
    PowerPointExtractor,
    WordExtractor,
)
from src.extraction.pdf_extractor import PdfExtractor
from src.extraction.text_extractor import PlainTextExtractor


# 登録順はマッチング優先度に影響しない（拡張子で一意に決まる）
_EXTRACTORS: list[TextExtractor] = [
    PlainTextExtractor(),
    WordExtractor(),
    ExcelExtractor(),
    PowerPointExtractor(),
    PdfExtractor(),
]


def get_extractor(file_path: Path) -> TextExtractor | None:
    """ファイルパスに対応する Extractor を返す。

    Args:
        file_path: 対象ファイルのパス。

    Returns:
        対応する :class:`TextExtractor`。
        サポートされていない拡張子の場合は ``None``。
    """
    for extractor in _EXTRACTORS:
        if extractor.can_extract(file_path):
            return extractor
    return None


def get_extractor_by_extension(extension: str) -> TextExtractor | None:
    """拡張子から対応する Extractor を返す。

    Args:
        extension: 拡張子（ドット有無・大小文字は問わない、例: ``"xlsx"`` / ``".XLSX"``）。

    Returns:
        対応する :class:`TextExtractor`。見つからない場合は ``None``。
    """
    ext = extension.lower().lstrip(".")
    for extractor in _EXTRACTORS:
        if ext in extractor.supported_extensions:
            return extractor
    return None


def get_supported_extensions() -> set[str]:
    """全 Extractor がサポートする拡張子の集合を返す（ドットなし小文字）。

    Returns:
        例: ``{"docx", "xlsx", "pptx", "pdf", "txt", "md", "log"}``
    """
    extensions: set[str] = set()
    for extractor in _EXTRACTORS:
        extensions.update(extractor.supported_extensions)
    return extensions
