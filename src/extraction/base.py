"""抽出機能の基底クラスとデータ構造。

全ての Extractor が共通で使用する :class:`ContentBlock`,
:class:`ExtractedContent`, :class:`TextExtractor` を定義する。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ContentBlock:
    """コンテンツブロック（段落・行・セル・スライドなどの単位）。

    ファイル種別によって設定されるフィールドが異なる。

    Attributes:
        text: ブロックのテキスト内容。
        page: ページ番号（1 始まり。PDF・Word 用）。
        sheet: シート名（Excel 用）。
        slide: スライド番号（1 始まり。PowerPoint 用）。
        line: 行番号（1 始まり。テキストファイル・Word 用）。
        cell: セル参照文字列（例: ``"A1"``。Excel 用）。
        heading_level: 見出しレベル（1–6。Word の見出しスタイル用）。
        is_slide_title: タイトルプレースホルダーか（PowerPoint 用）。
        list_level: リストのインデントレベル（0始まり。Word リスト項目用）。
        list_is_ordered: 順序付きリスト (True) か箇条書き (False) か。
    """

    text: str
    page: int | None = None
    sheet: str | None = None
    slide: int | None = None
    line: int | None = None
    cell: str | None = None
    heading_level: int | None = None
    is_slide_title: bool = False
    list_level: int | None = None      # リストのインデントレベル（0始まり。Word リスト用）
    list_is_ordered: bool = False      # 順序付きリスト (True) か箇条書き (False) か

    def get_location_info(self) -> str:
        """位置情報を人間が読める文字列で返す。

        設定済みのフィールド（page / sheet / slide / line / cell）を
        カンマ区切りで結合する。何も設定されていない場合は ``"不明"`` を返す。

        Returns:
            位置情報の文字列（例: ``"スライド 3"`` / ``"シート: Sheet1, セル A5"``）。
        """
        parts: list[str] = []
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
    """ファイルから抽出されたコンテンツ全体。

    Attributes:
        file_path: 抽出元ファイルのパス。
        blocks: 抽出されたコンテンツブロックのリスト。
        encoding: テキストファイルの文字コード（バイナリ系は ``None``）。
        total_pages: 総ページ数（PDF・Word 用）。
        total_sheets: 総シート数（Excel 用）。
        total_slides: 総スライド数（PowerPoint 用）。
        error: 抽出中にエラーが発生した場合のメッセージ。
    """

    file_path: Path
    blocks: list[ContentBlock] = field(default_factory=list)
    encoding: str | None = None
    total_pages: int | None = None
    total_sheets: int | None = None
    total_slides: int | None = None
    error: str | None = None

    @property
    def full_text(self) -> str:
        """全ブロックのテキストを改行で結合して返す。"""
        return "\n".join(block.text for block in self.blocks)

    @property
    def is_multipage(self) -> bool:
        """複数ページ・シート・スライドを持つかどうか。

        ナビゲーション UI の表示可否判定に使用する。
        """
        if self.total_pages is not None and self.total_pages > 1:
            return True
        if self.total_sheets is not None and self.total_sheets > 1:
            return True
        if self.total_slides is not None and self.total_slides > 1:
            return True
        return False


class TextExtractor(ABC):
    """テキスト抽出の抽象基底クラス。

    新しいファイル形式に対応するには、このクラスを継承して
    :attr:`supported_extensions` と :meth:`extract` を実装する。
    """

    @property
    @abstractmethod
    def supported_extensions(self) -> set[str]:
        """このExtractor がサポートする拡張子の集合（ドットなし小文字）。

        例: ``{"docx"}`` / ``{"xlsx"}`` / ``{"txt", "md", "log"}``
        """

    @abstractmethod
    def extract(self, file_path: Path) -> ExtractedContent:
        """ファイルからテキストを抽出して :class:`ExtractedContent` を返す。

        エラーが発生した場合は例外を送出せず、
        ``ExtractedContent.error`` にメッセージを設定して返すこと。

        Args:
            file_path: 抽出対象ファイルの絶対パス。

        Returns:
            抽出されたコンテンツ。エラー時は ``error`` フィールドが設定される。
        """

    def can_extract(self, file_path: Path) -> bool:
        """このExtractor がファイルを処理できるかどうかを返す。

        Args:
            file_path: 判定対象のファイルパス。

        Returns:
            ``True`` の場合、このExtractor で :meth:`extract` が呼び出せる。
        """
        ext = file_path.suffix.lower().lstrip(".")
        return ext in self.supported_extensions
