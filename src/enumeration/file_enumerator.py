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
    mtime_ns: int = 0  # キャッシュの鮮度判定用
    
    @classmethod
    def from_path(cls, path: Path, stat: Optional[os.stat_result] = None) -> "FileInfo":
        """パスからFileInfoを生成"""
        if stat is None:
            stat = path.stat()
        return cls(
            path=path,
            name=path.name,
            extension=extension_of(path.name),
            size=stat.st_size,
            modified_time=datetime.fromtimestamp(stat.st_mtime),
            mtime_ns=stat.st_mtime_ns,
        )


@dataclass
class EnumerationResult:
    """列挙結果"""
    files: list[FileInfo] = field(default_factory=list)
    extensions: set[str] = field(default_factory=set)
    total_size: int = 0
    error_count: int = 0


def extension_of(filename: str) -> str:
    """拡張子（ドットなし小文字）"""
    _, ext = os.path.splitext(filename)
    return ext.lower().lstrip(".")


def normalize_extensions(extensions) -> set[str]:
    """「.TXT」「txt」などの表記ゆれをそろえる"""
    return {e.strip().lower().lstrip(".") for e in extensions if e and e.strip().strip(".")}


def is_temporary_file(filename: str) -> bool:
    """Officeが編集中に作るロックファイル等（開けないので対象外にする）"""
    return filename.startswith("~$") or filename.startswith(".~lock.")


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
        directory = Path(directory)
        
        self._logger.info(
            "start",
            f"Enumerating directory: {directory}",
            include_subfolders=include_subfolders,
        )
        
        if target_extensions is None:
            target_extensions = self._config.target_extensions
        target_extensions = normalize_extensions(target_extensions)
        
        result = EnumerationResult()
        
        for file_info in self._walk_directory(directory, include_subfolders, target_extensions, result):
            if self._cancelled:
                self._logger.info("cancel", "Enumeration cancelled")
                break
            
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
            
            if progress_callback and len(result.files) % 200 == 0:
                progress_callback(len(result.files))
        
        # 表示順が実行ごとに変わらないようにする
        result.files.sort(key=lambda f: str(f.path).lower())
        
        self._logger.info(
            "end",
            f"Enumeration completed: {len(result.files)} files",
            file_count=len(result.files),
            total_size=result.total_size,
            extensions=sorted(result.extensions),
        )
        return result
    
    def _walk_directory(
        self,
        directory: Path,
        include_subfolders: bool,
        target_extensions: set[str],
        result: EnumerationResult,
    ) -> Iterator[FileInfo]:
        """ディレクトリを走査してファイル情報を生成
        
        os.scandir を使い、拡張子が対象外のファイルは stat せずに読み飛ばす。
        """
        stack = [str(directory)]
        
        while stack:
            if self._cancelled:
                return
            current = stack.pop()
            
            try:
                entries = os.scandir(current)
            except OSError as e:
                result.error_count += 1
                self._logger.warning(
                    "skip",
                    f"Cannot access directory: {current}",
                    exception_message=str(e),
                )
                continue
            
            with entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if include_subfolders:
                                stack.append(entry.path)
                            continue
                        
                        if is_temporary_file(entry.name):
                            continue
                        if extension_of(entry.name) not in target_extensions:
                            continue
                        if not entry.is_file():
                            continue
                        
                        yield FileInfo.from_path(Path(entry.path), entry.stat())
                    
                    except OSError as e:
                        result.error_count += 1
                        self._logger.warning(
                            "skip",
                            f"Cannot access file: {entry.path}",
                            file_path=entry.path,
                            exception_message=str(e),
                        )
    
    def get_extensions_in_directory(
        self,
        directory: Path,
        include_subfolders: bool = True,
    ) -> set[str]:
        """ディレクトリ内に存在する拡張子一覧を取得"""
        extensions: set[str] = set()
        stack = [str(directory)]
        
        while stack:
            try:
                with os.scandir(stack.pop()) as entries:
                    for entry in entries:
                        if entry.is_dir(follow_symlinks=False):
                            if include_subfolders:
                                stack.append(entry.path)
                        elif ext := extension_of(entry.name):
                            extensions.add(ext)
            except OSError as e:
                self._logger.warning("error", f"Cannot scan directory: {directory}", exception_message=str(e))
        
        return extensions
