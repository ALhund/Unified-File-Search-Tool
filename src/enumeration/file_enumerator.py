"""ファイル列挙モジュール

指定ディレクトリ配下のファイルを列挙し、拡張子一覧を生成する。
"""

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator, Optional

from src.common.config import get_config
from src.common.logger import get_logger


@dataclass
class FileInfo:
    """ファイル情報"""
    path: Path
    name: str
    extension: str  # ドットなし小文字（例: "xlsx"）
    size: int  # バイト単位
    modified_time: datetime
    
    @classmethod
    def from_path(cls, path: Path) -> "FileInfo":
        """パスからFileInfoを生成"""
        stat = path.stat()
        ext = path.suffix.lower().lstrip(".")
        return cls(
            path=path,
            name=path.name,
            extension=ext,
            size=stat.st_size,
            modified_time=datetime.fromtimestamp(stat.st_mtime),
        )


@dataclass
class EnumerationResult:
    """列挙結果"""
    files: list[FileInfo] = field(default_factory=list)
    extensions: set[str] = field(default_factory=set)
    total_size: int = 0
    error_count: int = 0


class FileEnumerator:
    """ファイル列挙クラス"""
    
    def __init__(self):
        self._logger = get_logger("enumeration")
        self._config = get_config()
        self._cancelled = False
    
    def cancel(self) -> None:
        """列挙をキャンセル"""
        self._cancelled = True
    
    def reset(self) -> None:
        """キャンセル状態をリセット"""
        self._cancelled = False
    
    def enumerate(
        self,
        directory: Path,
        include_subfolders: bool = True,
        target_extensions: Optional[set[str]] = None,
        max_file_size: Optional[int] = None,
        min_modified: Optional[datetime] = None,
        max_modified: Optional[datetime] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> EnumerationResult:
        """ディレクトリ内のファイルを列挙
        
        Args:
            directory: 対象ディレクトリ
            include_subfolders: サブフォルダも含めるか
            target_extensions: 対象拡張子（Noneの場合は設定から取得）
            max_file_size: 最大ファイルサイズ（バイト）
            min_modified: 更新日の下限
            max_modified: 更新日の上限
            progress_callback: 進捗コールバック（ファイル数）
        
        Returns:
            列挙結果
        """
        self._cancelled = False
        correlation_id = self._logger.set_correlation_id()
        
        self._logger.info("start", f"Enumerating directory: {directory}", extra={
            "include_subfolders": include_subfolders,
        })
        
        if target_extensions is None:
            target_extensions = set(self._config.target_extensions)
        
        result = EnumerationResult()
        file_count = 0
        
        try:
            for file_info in self._walk_directory(directory, include_subfolders):
                if self._cancelled:
                    self._logger.info("cancel", "Enumeration cancelled")
                    break
                
                # 拡張子フィルタ
                if file_info.extension not in target_extensions:
                    continue
                
                # サイズフィルタ
                if max_file_size is not None and file_info.size > max_file_size:
                    continue
                
                # 更新日フィルタ
                if min_modified is not None and file_info.modified_time < min_modified:
                    continue
                if max_modified is not None and file_info.modified_time > max_modified:
                    continue
                
                result.files.append(file_info)
                result.extensions.add(file_info.extension)
                result.total_size += file_info.size
                
                file_count += 1
                if progress_callback:
                    progress_callback(file_count)
            
            self._logger.info("end", f"Enumeration completed: {len(result.files)} files", extra={
                "file_count": len(result.files),
                "total_size": result.total_size,
                "extensions": list(result.extensions),
            })
        
        except Exception as e:
            self._logger.exception("error", f"Enumeration failed: {e}", e)
            raise
        
        finally:
            self._logger.clear_correlation_id()
        
        return result
    
    def _walk_directory(
        self,
        directory: Path,
        include_subfolders: bool,
    ) -> Iterator[FileInfo]:
        """ディレクトリを走査してファイル情報を生成"""
        try:
            if include_subfolders:
                for root, dirs, files in os.walk(directory):
                    if self._cancelled:
                        return
                    
                    root_path = Path(root)
                    for filename in files:
                        if self._cancelled:
                            return
                        
                        file_path = root_path / filename
                        try:
                            yield FileInfo.from_path(file_path)
                        except (OSError, PermissionError) as e:
                            self._logger.warning(
                                "skip",
                                f"Cannot access file: {file_path}",
                                file_path=str(file_path),
                                exception_message=str(e),
                            )
            else:
                for item in directory.iterdir():
                    if self._cancelled:
                        return
                    
                    if item.is_file():
                        try:
                            yield FileInfo.from_path(item)
                        except (OSError, PermissionError) as e:
                            self._logger.warning(
                                "skip",
                                f"Cannot access file: {item}",
                                file_path=str(item),
                                exception_message=str(e),
                            )
        
        except (OSError, PermissionError) as e:
            self._logger.exception("error", f"Cannot access directory: {directory}", e)
    
    def get_extensions_in_directory(
        self,
        directory: Path,
        include_subfolders: bool = True,
    ) -> set[str]:
        """ディレクトリ内に存在する拡張子一覧を取得"""
        extensions = set()
        
        try:
            if include_subfolders:
                for root, dirs, files in os.walk(directory):
                    for filename in files:
                        ext = Path(filename).suffix.lower().lstrip(".")
                        if ext:
                            extensions.add(ext)
            else:
                for item in directory.iterdir():
                    if item.is_file():
                        ext = item.suffix.lower().lstrip(".")
                        if ext:
                            extensions.add(ext)
        
        except (OSError, PermissionError) as e:
            self._logger.warning("error", f"Cannot scan directory: {directory}", exception_message=str(e))
        
        return extensions
