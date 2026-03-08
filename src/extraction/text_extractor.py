"""プレーンテキスト抽出モジュール（.txt / .md / .log）。

文字コードを自動判別し、行単位で :class:`ContentBlock` を生成する。
.log ファイルに対しては制御文字除去・左詰め処理を追加適用する。
"""

from pathlib import Path

from src.common.logger import get_logger
from src.common.utils import (
    decode_with_fallback,
    normalize_newlines,
    sanitize_control_chars,
    strip_leading_whitespace_per_line,
)
from src.extraction.base import ContentBlock, ExtractedContent, TextExtractor


class PlainTextExtractor(TextExtractor):
    """プレーンテキストファイル（.txt / .md / .log）から抽出する Extractor。

    バイトとして読み込んだ後に :func:`decode_with_fallback` で
    文字コードを判別・デコードし、行単位でブロックを生成する。
    """

    def __init__(self) -> None:
        self._logger = get_logger("extraction")

    @property
    def supported_extensions(self) -> set[str]:
        """サポートする拡張子: ``{"txt", "md", "log"}``。"""
        return {"txt", "md", "log"}

    def extract(self, file_path: Path) -> ExtractedContent:
        """テキストファイルからコンテンツを抽出する。

        処理フロー:

        1. バイナリ読み込み
        2. :func:`decode_with_fallback` で文字コード判別・デコード
        3. 改行コードを LF に統一（:func:`normalize_newlines`）
        4. ``.log`` の場合は制御文字除去・左詰めを追加適用
        5. 空行を除いた各行を :class:`ContentBlock` として追加

        Args:
            file_path: 抽出対象のテキストファイルパス。

        Returns:
            抽出されたコンテンツ。エラー時は ``error`` が設定される。
        """
        result = ExtractedContent(file_path=file_path)

        try:
            data = file_path.read_bytes()
            text, encoding = decode_with_fallback(data)
            result.encoding = encoding

            text = normalize_newlines(text)

            # .log ファイル固有の追加処理
            if file_path.suffix.lower().lstrip(".") == "log":
                text = sanitize_control_chars(text, keep_newlines=True)
                text = strip_leading_whitespace_per_line(text)

            for line_num, line_text in enumerate(text.split("\n"), start=1):
                if line_text.strip():
                    result.blocks.append(ContentBlock(
                        text=line_text,
                        line=line_num,
                    ))

            result.total_pages = 1

            self._logger.debug(
                "extract",
                f"Extracted {len(result.blocks)} blocks from text file",
                file_path=str(file_path),
                encoding=encoding,
            )

        except Exception as exc:
            result.error = str(exc)
            self._logger.exception(
                "error",
                f"Failed to extract text from {file_path}",
                exc,
                file_path=str(file_path),
            )

        return result
