"""プレーンテキスト抽出モジュール（txt, md, log）"""

from pathlib import Path

from src.common.logger import get_logger
from src.common.utils import (
    decode_with_fallback,
    normalize_newlines,
    sanitize_control_chars,
    strip_leading_whitespace_per_line,
)
from src.extraction.base import TextExtractor, ExtractedContent, ContentBlock


class PlainTextExtractor(TextExtractor):
    """プレーンテキストファイルの抽出"""
    
    def __init__(self):
        self._logger = get_logger("extraction")
    
    @property
    def supported_extensions(self) -> set[str]:
        return {"txt", "md", "log"}
    
    def extract(self, file_path: Path) -> ExtractedContent:
        """テキストファイルからコンテンツを抽出"""
        result = ExtractedContent(file_path=file_path)
        
        try:
            # バイナリで読み込み
            data = Path(file_path).read_bytes()
            
            # 文字コード判別とデコード
            text, encoding = decode_with_fallback(data)
            result.encoding = encoding
            
            # 改行正規化
            text = normalize_newlines(text)
            
            # .log ファイルの場合は追加処理
            ext = file_path.suffix.lower().lstrip(".")
            if ext == "log":
                # 制御文字除去（改行は保持）
                text = sanitize_control_chars(text, keep_newlines=True)
                # 左詰め
                text = strip_leading_whitespace_per_line(text)
            
            # 行単位でContentBlockを生成
            lines = text.split("\n")
            for line_num, line_text in enumerate(lines, start=1):
                if line_text.strip():  # 空行はスキップ
                    result.blocks.append(ContentBlock(
                        text=line_text,
                        line=line_num,
                    ))
            
            result.total_lines = len(lines)
            
            self._logger.debug(
                "extract",
                f"Extracted {len(result.blocks)} blocks from text file",
                file_path=str(file_path),
                encoding=encoding,
            )
        
        except Exception as e:
            result.error = str(e)
            self._logger.exception(
                "error",
                f"Failed to extract text from {file_path}",
                e,
                file_path=str(file_path),
            )
        
        return result
