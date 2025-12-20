"""抽出機能の基底クラスとデータ構造"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ContentBlock:
    """コンテンツブロック（段落/行/セル/スライド等の単位）"""
    text: str
    page: Optional[int] = None  # ページ番号（1始まり）
    sheet: Optional[str] = None  # シート名
    slide: Optional[int] = None  # スライド番号（1始まり）
    line: Optional[int] = None  # 行番号（1始まり）
    cell: Optional[str] = None  # セル参照（例: "A1"）
    
    def get_location_info(self) -> str:
        """位置情報を文字列で取得"""
        parts = []
        if self.page is not None:
            parts.append(f"ページ {self.page}")
        if self.sheet is not None:
            parts.append(f"シート: {self.sheet}")
        if self.slide is not None:
            parts.append(f"スライド {self.slide}")
        if self.line is not None:
            parts.append(f"行 {self.line}")
        if self.cell is not None:
            parts.append(f"セル {self.cell}")
        return ", ".join(parts) if parts else "不明"


@dataclass
class ExtractedContent:
    """抽出されたコンテンツ"""
    file_path: Path
    blocks: list[ContentBlock] = field(default_factory=list)
    encoding: Optional[str] = None  # テキストファイルの場合の文字コード
    total_pages: Optional[int] = None  # 総ページ数
    total_sheets: Optional[int] = None  # 総シート数
    total_slides: Optional[int] = None  # 総スライド数
    error: Optional[str] = None  # エラーがあった場合
    
    @property
    def full_text(self) -> str:
        """全テキストを結合して返す"""
        return "\n".join(block.text for block in self.blocks)
    
    @property
    def is_multipage(self) -> bool:
        """複数ページ/シート/スライドを持つか"""
        if self.total_pages is not None and self.total_pages > 1:
            return True
        if self.total_sheets is not None and self.total_sheets > 1:
            return True
        if self.total_slides is not None and self.total_slides > 1:
            return True
        return False


class TextExtractor(ABC):
    """テキスト抽出の基底クラス"""
    
    @property
    @abstractmethod
    def supported_extensions(self) -> set[str]:
        """サポートする拡張子（ドットなし小文字）"""
        pass
    
    @abstractmethod
    def extract(self, file_path: Path) -> ExtractedContent:
        """ファイルからテキストを抽出
        
        Args:
            file_path: 対象ファイルのパス
        
        Returns:
            抽出されたコンテンツ
        """
        pass
    
    def can_extract(self, file_path: Path) -> bool:
        """このExtractorで処理可能か"""
        ext = file_path.suffix.lower().lstrip(".")
        return ext in self.supported_extensions
