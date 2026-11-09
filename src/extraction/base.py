"""抽出機能の基底クラスとデータ構造"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# ブロック種別ごとの表示名（本文・セルは表示しない）
KIND_LABELS = {
    "shape": "図形",
    "chart": "グラフ",
    "note": "ノート",
    "header": "ヘッダー",
    "footer": "フッター",
    "table": "表",
}


@dataclass(eq=False)
class ContentBlock:
    """コンテンツブロック（段落/行/セル/図形等の単位）"""
    text: str
    page: Optional[int] = None  # ページ番号（1始まり）
    sheet: Optional[str] = None  # シート名
    slide: Optional[int] = None  # スライド番号（1始まり）
    line: Optional[int] = None  # 行番号・段落番号（1始まり）
    cell: Optional[str] = None  # セル参照（例: "A1"）
    kind: Optional[str] = None  # heading / shape / chart / note / header / footer / table
    table: Optional[tuple[int, int, int]] = None  # (表番号, 行, 列) 0始まり
    
    def get_location_info(self) -> str:
        """位置情報を文字列で取得"""
        parts = []
        if self.page is not None:
            parts.append(f"ページ {self.page}")
        if self.sheet is not None:
            parts.append(f"シート: {self.sheet}")
        if self.slide is not None:
            parts.append(f"スライド {self.slide}")
        if self.kind in KIND_LABELS:
            parts.append(KIND_LABELS[self.kind])
        if self.line is not None:
            parts.append(f"行 {self.line}")
        if self.cell is not None:
            parts.append(f"セル {self.cell}")
        return ", ".join(parts) if parts else "本文"


@dataclass
class ExtractedContent:
    """抽出されたコンテンツ"""
    file_path: Path
    blocks: list[ContentBlock] = field(default_factory=list)
    encoding: Optional[str] = None  # テキストファイルの場合の文字コード
    total_pages: Optional[int] = None  # 総ページ数
    total_sheets: Optional[int] = None  # 総シート数
    total_slides: Optional[int] = None  # 総スライド数
    total_lines: Optional[int] = None  # テキストファイルの総行数
    error: Optional[str] = None  # エラーがあった場合
    
    @property
    def full_text(self) -> str:
        """全テキストを結合して返す"""
        return "\n".join(block.text for block in self.blocks)
    
    @property
    def is_multipage(self) -> bool:
        """複数ページ/シート/スライドを持つか"""
        return any(
            n is not None and n > 1
            for n in (self.total_pages, self.total_sheets, self.total_slides)
        )
    
    def to_dict(self) -> dict:
        """キャッシュ保存用の辞書に変換"""
        data = asdict(self)
        data["file_path"] = str(self.file_path)
        return data
    
    @classmethod
    def from_dict(cls, data: dict) -> "ExtractedContent":
        blocks = []
        for b in data.get("blocks", []):
            if b.get("table") is not None:
                b["table"] = tuple(b["table"])
            blocks.append(ContentBlock(**b))
        fields = {k: v for k, v in data.items() if k not in ("blocks", "file_path")}
        return cls(file_path=Path(data["file_path"]), blocks=blocks, **fields)


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
        ext = Path(file_path).suffix.lower().lstrip(".")
        return ext in self.supported_extensions
