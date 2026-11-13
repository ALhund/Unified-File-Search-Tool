"""メタデータ取得モジュール

Officeファイルのプロパティ（作者/作成日）を取得する。
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.common.logger import get_logger


@dataclass
class FileMetadata:
    """ファイルメタデータ"""
    author: Optional[str] = None
    created: Optional[datetime] = None
    modified: Optional[datetime] = None
    last_modified_by: Optional[str] = None
    title: Optional[str] = None
    
    @property
    def display_author(self) -> str:
        """表示用の作者（Last Modified By優先）"""
        return self.last_modified_by or self.author or "不明"
    
    @property
    def display_created(self) -> str:
        """表示用の作成日（Created優先、なければModified）"""
        dt = self.created or self.modified
        if dt:
            return dt.strftime("%Y/%m/%d %H:%M")
        return "不明"


class MetadataReader:
    """メタデータ読み取りクラス"""
    
    def __init__(self):
        self._logger = get_logger("metadata")
    
    def read(self, file_path: Path) -> FileMetadata:
        """ファイルのメタデータを読み取る"""
        ext = file_path.suffix.lower().lstrip(".")
        
        try:
            if ext == "docx":
                return self._read_docx(file_path)
            elif ext == "xlsx":
                return self._read_xlsx(file_path)
            elif ext == "pptx":
                return self._read_pptx(file_path)
            elif ext == "pdf":
                return self._read_pdf(file_path)
            elif ext in ("xls", "doc", "ppt"):
                return self._read_ole(file_path)
            else:
                # テキスト系はファイルシステムのタイムスタンプのみ
                return self._read_filesystem(file_path)
        
        except Exception as e:
            self._logger.warning(
                "error",
                f"Failed to read metadata: {file_path}",
                file_path=str(file_path),
                exception_message=str(e),
            )
            return FileMetadata()
    
    def _read_docx(self, file_path: Path) -> FileMetadata:
        """Wordファイルのメタデータを読み取る"""
        from docx import Document
        
        doc = Document(file_path)
        props = doc.core_properties
        
        return FileMetadata(
            author=props.author,
            created=props.created,
            modified=props.modified,
            last_modified_by=props.last_modified_by,
            title=props.title,
        )
    
    def _read_xlsx(self, file_path: Path) -> FileMetadata:
        """Excelファイルのメタデータを読み取る"""
        from openpyxl import load_workbook
        
        wb = load_workbook(file_path, read_only=True, data_only=True)
        props = wb.properties
        
        metadata = FileMetadata(
            author=props.creator,
            created=props.created,
            modified=props.modified,
            last_modified_by=props.lastModifiedBy,
            title=props.title,
        )
        
        wb.close()
        return metadata
    
    def _read_pptx(self, file_path: Path) -> FileMetadata:
        """PowerPointファイルのメタデータを読み取る"""
        from pptx import Presentation
        
        prs = Presentation(file_path)
        props = prs.core_properties
        
        return FileMetadata(
            author=props.author,
            created=props.created,
            modified=props.modified,
            last_modified_by=props.last_modified_by,
            title=props.title,
        )
    
    def _read_ole(self, file_path: Path) -> FileMetadata:
        """旧形式の Office（OLE 複合ファイル）のプロパティ"""
        import olefile
        
        with olefile.OleFileIO(str(file_path)) as ole:
            meta = ole.get_metadata()
        
        def text(value) -> Optional[str]:
            if isinstance(value, bytes):
                for encoding in ("utf-8", "cp932", "latin-1"):
                    try:
                        return value.decode(encoding).strip("\x00 ") or None
                    except UnicodeDecodeError:
                        continue
            return value or None
        
        return FileMetadata(
            author=text(meta.author),
            created=meta.create_time,
            modified=meta.last_saved_time,
            last_modified_by=text(meta.last_saved_by),
            title=text(meta.title),
        )
    
    def _read_pdf(self, file_path: Path) -> FileMetadata:
        """PDFファイルのメタデータを読み取る"""
        from src.common.pdf_layout import PDFIUM_LOCK, open_document
        
        with PDFIUM_LOCK:
            doc = open_document(file_path)
            try:
                meta = doc.get_metadata_dict(skip_empty=True)
            finally:
                doc.close()
        
        metadata = FileMetadata()
        if meta:
            metadata.author = meta.get("Author")
            metadata.title = meta.get("Title")
            
            # 日付のパース（PDF形式: D:YYYYMMDDHHmmSS）
            if creation_date := meta.get("CreationDate"):
                metadata.created = self._parse_pdf_date(creation_date)
            if mod_date := meta.get("ModDate"):
                metadata.modified = self._parse_pdf_date(mod_date)
        return metadata
    
    def _parse_pdf_date(self, date_str: str) -> Optional[datetime]:
        """PDF形式の日付をパース"""
        if not date_str:
            return None
        
        # D:YYYYMMDDHHmmSS 形式
        try:
            if date_str.startswith("D:"):
                date_str = date_str[2:]
            
            # タイムゾーン部分を除去
            for sep in ["+", "-", "Z"]:
                if sep in date_str:
                    date_str = date_str.split(sep)[0]
            
            # 長さに応じてパース
            if len(date_str) >= 14:
                return datetime.strptime(date_str[:14], "%Y%m%d%H%M%S")
            elif len(date_str) >= 8:
                return datetime.strptime(date_str[:8], "%Y%m%d")
        except ValueError:
            pass
        
        return None
    
    def _read_filesystem(self, file_path: Path) -> FileMetadata:
        """ファイルシステムからメタデータを読み取る"""
        stat = file_path.stat()
        
        return FileMetadata(
            created=datetime.fromtimestamp(stat.st_ctime),
            modified=datetime.fromtimestamp(stat.st_mtime),
        )
