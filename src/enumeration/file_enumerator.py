"""ファイル列挙モジュール。

指定ディレクトリ配下のファイルを走査し、フィルタリングして列挙する。
拡張子・ファイルサイズ・更新日時によるフィルタに対応する。
"""

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

from src.common.config import get_config
from src.common.logger import get_logger


@dataclass
class FileInfo:
    """ファイルのメタ情報を保持するデータクラス。

    Attributes:
        path: ファイルの絶対パス。
        name: ファイル名（拡張子を含む）。
        extension: 拡張子（ドットなし小文字、例: ``"xlsx"``）。
        size: ファイルサイズ（バイト単位）。
        modified_time: 最終更新日時。
    """

    path: Path
    name: str
    extension: str
    size: int
    modified_time: datetime

    @classmethod
    def from_path(cls, path: Path) -> "FileInfo":
        """パスから FileInfo を生成する。

        Args:
            path: 対象ファイルのパス。

        Returns:
            対応する FileInfo インスタンス。

        Raises:
            OSError: ファイルへのアクセスに失敗した場合。
        """
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
    """ファイル列挙の結果を保持するデータクラス。

    Attributes:
        files: 列挙されたファイル情報のリスト。
        extensions: 見つかった拡張子の集合（ドットなし小文字）。
        total_size: 全ファイルの合計サイズ（バイト単位）。
        error_count: アクセスエラーが発生したファイル数。
    """

    files: list[FileInfo] = field(default_factory=list)
    extensions: set[str] = field(default_factory=set)
    total_size: int = 0
    error_count: int = 0


class FileEnumerator:
    """ディレクトリを再帰的に走査してファイルを列挙するクラス。

    キャンセル操作（:meth:`cancel`）をサポートしており、
    長時間の走査を中断できる。
    """

    def __init__(self) -> None:
        self._logger = get_logger("enumeration")
        self._config = get_config()
        self._cancelled = False

    def cancel(self) -> None:
        """進行中の列挙をキャンセルする。"""
        self._cancelled = True

    def reset(self) -> None:
        """キャンセル状態をリセットする（次回呼び出し前に実行すること）。"""
        self._cancelled = False

    def enumerate(
        self,
        directory: Path,
        include_subfolders: bool = True,
        target_extensions: set[str] | None = None,
        max_file_size: int | None = None,
        min_modified: datetime | None = None,
        max_modified: datetime | None = None,
        progress_callback: Callable[[int], None] | None = None,
    ) -> EnumerationResult:
        """ディレクトリ内のファイルを列挙してフィルタリングする。

        Args:
            directory: 走査対象のディレクトリ。
            include_subfolders: ``True`` の場合、サブフォルダも再帰的に走査する。
            target_extensions: 対象拡張子の集合（ドットなし小文字）。
                               ``None`` の場合は設定ファイルの値を使用する。
            max_file_size: 最大ファイルサイズ（バイト）。超えるファイルは除外する。
            min_modified: 更新日時の下限。これより古いファイルは除外する。
            max_modified: 更新日時の上限。これより新しいファイルは除外する。
            progress_callback: マッチしたファイル数を引数として受け取るコールバック。

        Returns:
            列挙・フィルタリング後の :class:`EnumerationResult`。
        """
        self._cancelled = False
        self._logger.set_correlation_id()

        self._logger.info(
            "start",
            f"Enumerating directory: {directory}",
            include_subfolders=include_subfolders,
        )

        if target_extensions is None:
            target_extensions = set(self._config.target_extensions)

        result = EnumerationResult()
        file_count = 0

        try:
            for file_info in self._walk_directory(directory, include_subfolders):
                if self._cancelled:
                    self._logger.info("cancel", "Enumeration cancelled")
                    break

                if file_info.extension not in target_extensions:
                    continue
                if max_file_size is not None and file_info.size > max_file_size:
                    continue
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

            self._logger.info(
                "end",
                f"Enumeration completed: {len(result.files)} files",
                file_count=len(result.files),
                total_size=result.total_size,
                extensions=list(result.extensions),
            )

        except Exception as exc:
            self._logger.exception("error", f"Enumeration failed: {exc}", exc)
            raise

        finally:
            self._logger.clear_correlation_id()

        return result

    def get_extensions_in_directory(
        self,
        directory: Path,
        include_subfolders: bool = True,
    ) -> set[str]:
        """ディレクトリ内に存在する全拡張子の集合を取得する。

        フィルタリングは行わず、存在する拡張子を列挙するだけの軽量メソッド。

        Args:
            directory: 走査対象のディレクトリ。
            include_subfolders: ``True`` の場合、サブフォルダも走査する。

        Returns:
            拡張子の集合（ドットなし小文字）。
        """
        extensions: set[str] = set()

        try:
            if include_subfolders:
                for root, _dirs, files in os.walk(directory):
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

        except (OSError, PermissionError) as exc:
            self._logger.warning(
                "error",
                f"Cannot scan directory: {directory}",
                exception_message=str(exc),
            )

        return extensions

    # ------------------------------------------------------------------
    # 内部ヘルパー
    # ------------------------------------------------------------------

    def _walk_directory(
        self,
        directory: Path,
        include_subfolders: bool,
    ) -> Iterator[FileInfo]:
        """ディレクトリを走査して FileInfo をひとつずつ生成するジェネレータ。

        アクセスエラーが発生した個別ファイルは警告ログを残してスキップする。
        ディレクトリ自体へのアクセスエラーは例外を記録して走査を終了する。

        Args:
            directory: 走査対象のディレクトリ。
            include_subfolders: ``True`` の場合、サブフォルダも走査する。

        Yields:
            列挙された各ファイルの :class:`FileInfo`。
        """
        try:
            if include_subfolders:
                for root, _dirs, files in os.walk(directory):
                    if self._cancelled:
                        return
                    root_path = Path(root)
                    for filename in files:
                        if self._cancelled:
                            return
                        file_path = root_path / filename
                        try:
                            yield FileInfo.from_path(file_path)
                        except (OSError, PermissionError) as exc:
                            self._logger.warning(
                                "skip",
                                f"Cannot access file: {file_path}",
                                file_path=str(file_path),
                                exception_message=str(exc),
                            )
            else:
                for item in directory.iterdir():
                    if self._cancelled:
                        return
                    if item.is_file():
                        try:
                            yield FileInfo.from_path(item)
                        except (OSError, PermissionError) as exc:
                            self._logger.warning(
                                "skip",
                                f"Cannot access file: {item}",
                                file_path=str(item),
                                exception_message=str(exc),
                            )

        except (OSError, PermissionError) as exc:
            self._logger.exception(
                "error",
                f"Cannot access directory: {directory}",
                exc,
            )
