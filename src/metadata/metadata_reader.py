"""メタデータ取得モジュール。

Office 系ファイル・PDF のコアプロパティ（作成者・作成日）とファイルシステム
タイムスタンプを読み取り、統一された :class:`FileMetadata` として返す。
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.common.logger import get_logger


@dataclass
class FileMetadata:
    """ファイルのメタデータを保持するデータクラス。

    Attributes:
        author: 作成者名（ドキュメントプロパティから取得）。
        created: 作成日時。
        modified: 最終更新日時。
        last_modified_by: 最終更新者名（Office 用）。
        title: ドキュメントタイトル。
    """

    author: str | None = None
    created: datetime | None = None
    modified: datetime | None = None
    last_modified_by: str | None = None
    title: str | None = None

    @property
    def display_author(self) -> str:
        """表示用の作成者名を返す（最終更新者を優先）。

        ``last_modified_by`` → ``author`` の順に確認し、
        どちらも設定されていない場合は ``"不明"`` を返す。
        """
        return self.last_modified_by or self.author or "不明"

    @property
    def display_created(self) -> str:
        """表示用の作成日時文字列を返す（created を優先）。

        ``created`` → ``modified`` の順に確認し、
        どちらも設定されていない場合は ``"不明"`` を返す。
        """
        dt = self.created or self.modified
        if dt:
            return dt.strftime("%Y/%m/%d %H:%M")
        return "不明"


class MetadataReader:
    """ファイルのメタデータを読み取るクラス。

    拡張子に応じて Office 系ライブラリ・PyMuPDF・
    ファイルシステム API を使い分ける。
    """

    def __init__(self) -> None:
        self._logger = get_logger("metadata")

    def read(self, file_path: Path) -> FileMetadata:
        """ファイルのメタデータを読み取る。

        対応形式（docx / xlsx / pptx / pdf）はそれぞれ専用メソッドで処理し、
        それ以外はファイルシステムのタイムスタンプを返す。
        エラーが発生した場合は警告ログを残して空の :class:`FileMetadata` を返す。

        Args:
            file_path: メタデータを読み取る対象ファイルのパス。

        Returns:
            読み取ったメタデータ。エラー時はデフォルト値（全 ``None``）のインスタンス。
        """
        ext = file_path.suffix.lower().lstrip(".")

        try:
            if ext == "docx":
                return self._read_docx(file_path)
            if ext == "xlsx":
                return self._read_xlsx(file_path)
            if ext == "pptx":
                return self._read_pptx(file_path)
            if ext == "pdf":
                return self._read_pdf(file_path)
            return self._read_filesystem(file_path)

        except Exception as exc:
            self._logger.warning(
                "error",
                f"Failed to read metadata: {file_path}",
                file_path=str(file_path),
                exception_message=str(exc),
            )
            return FileMetadata()

    # ------------------------------------------------------------------
    # 形式別読み取りメソッド
    # ------------------------------------------------------------------

    def _read_docx(self, file_path: Path) -> FileMetadata:
        """Word ファイル（.docx）のコアプロパティを読み取る。

        Args:
            file_path: 対象の .docx ファイルパス。

        Returns:
            読み取った :class:`FileMetadata`。
        """
        from docx import Document

        doc = Document(file_path)
        props = doc.core_properties
        return FileMetadata(
            author=props.author or None,
            created=props.created,
            modified=props.modified,
            last_modified_by=props.last_modified_by or None,
            title=props.title or None,
        )

    def _read_xlsx(self, file_path: Path) -> FileMetadata:
        """Excel ファイル（.xlsx）のコアプロパティを読み取る。

        Args:
            file_path: 対象の .xlsx ファイルパス。

        Returns:
            読み取った :class:`FileMetadata`。
        """
        from openpyxl import load_workbook

        wb = load_workbook(file_path, read_only=True, data_only=True)
        props = wb.properties
        metadata = FileMetadata(
            author=props.creator or None,
            created=props.created,
            modified=props.modified,
            last_modified_by=props.lastModifiedBy or None,
            title=props.title or None,
        )
        wb.close()
        return metadata

    def _read_pptx(self, file_path: Path) -> FileMetadata:
        """PowerPoint ファイル（.pptx）のコアプロパティを読み取る。

        Args:
            file_path: 対象の .pptx ファイルパス。

        Returns:
            読み取った :class:`FileMetadata`。
        """
        from pptx import Presentation

        prs = Presentation(file_path)
        props = prs.core_properties
        return FileMetadata(
            author=props.author or None,
            created=props.created,
            modified=props.modified,
            last_modified_by=props.last_modified_by or None,
            title=props.title or None,
        )

    def _read_pdf(self, file_path: Path) -> FileMetadata:
        """PDF ファイルのメタデータを PyMuPDF で読み取る。

        PDF 日付形式（``D:YYYYMMDDHHmmSS``）は :meth:`_parse_pdf_date` でパースする。

        Args:
            file_path: 対象の .pdf ファイルパス。

        Returns:
            読み取った :class:`FileMetadata`。
        """
        import fitz  # PyMuPDF

        doc = fitz.open(file_path)
        meta = doc.metadata
        metadata = FileMetadata()

        if meta:
            metadata.author = meta.get("author") or None
            metadata.title = meta.get("title") or None
            if creation_date := meta.get("creationDate"):
                metadata.created = self._parse_pdf_date(creation_date)
            if mod_date := meta.get("modDate"):
                metadata.modified = self._parse_pdf_date(mod_date)

        doc.close()
        return metadata

    def _read_filesystem(self, file_path: Path) -> FileMetadata:
        """ファイルシステムの ctime / mtime を読み取る。

        Office・PDF 以外のテキストファイル用のフォールバック。

        Args:
            file_path: 対象ファイルパス。

        Returns:
            ファイルシステムタイムスタンプを持つ :class:`FileMetadata`。
        """
        stat = file_path.stat()
        return FileMetadata(
            created=datetime.fromtimestamp(stat.st_ctime),
            modified=datetime.fromtimestamp(stat.st_mtime),
        )

    # ------------------------------------------------------------------
    # 内部ヘルパー
    # ------------------------------------------------------------------

    def _parse_pdf_date(self, date_str: str) -> datetime | None:
        """PDF 形式の日付文字列を :class:`datetime` に変換する。

        対応フォーマット: ``D:YYYYMMDDHHmmSS[+HH'mm']`` など。
        タイムゾーン情報は無視する。

        Args:
            date_str: PDF メタデータの日付文字列。

        Returns:
            パース成功時は :class:`datetime`、失敗時は ``None``。
        """
        if not date_str:
            return None

        try:
            if date_str.startswith("D:"):
                date_str = date_str[2:]

            # タイムゾーン部分を除去
            for sep in ("+", "-", "Z"):
                if sep in date_str:
                    date_str = date_str.split(sep)[0]
                    break

            if len(date_str) >= 14:
                return datetime.strptime(date_str[:14], "%Y%m%d%H%M%S")
            if len(date_str) >= 8:
                return datetime.strptime(date_str[:8], "%Y%m%d")

        except ValueError:
            pass

        return None
