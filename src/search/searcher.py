"""検索モジュール。

ファイル内容を検索して :class:`MatchInfo` / :class:`SearchResult` を返す。
キャンセル操作（:meth:`Searcher.cancel`）をサポートし、
長時間の検索を中断できる。
"""

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from src.common.config import get_config
from src.common.logger import get_logger
from src.enumeration import FileInfo
from src.extraction import ExtractedContent, ContentBlock, get_extractor


@dataclass
class SearchOptions:
    """検索オプションを保持するデータクラス。

    Attributes:
        query: 検索クエリ文字列。
        case_sensitive: 大文字小文字を区別するか（``use_regex=False`` 時のみ有効）。
        use_regex: ``True`` の場合、query を正規表現として扱う。
        match_whole: 全文一致モード（ブロック全体がクエリに一致する場合のみマッチ）。
        exclude_words: 除外キーワードのリスト（含まれるブロックをスキップ）。
        regex_ignore_case: 正規表現モード時の大文字小文字無視フラグ。
        regex_multiline: 正規表現モード時のマルチラインフラグ。
        regex_dot_matches_newline: 正規表現モード時の DOTALL フラグ。
    """

    query: str
    case_sensitive: bool = False
    use_regex: bool = False
    match_whole: bool = False
    exclude_words: list[str] = field(default_factory=list)
    regex_ignore_case: bool = True
    regex_multiline: bool = False
    regex_dot_matches_newline: bool = False

    def get_regex_flags(self) -> int:
        """正規表現コンパイル用のフラグ整数を返す。

        Returns:
            ``re`` モジュールのフラグの OR 結合値。
        """
        flags = 0
        if not self.case_sensitive and self.regex_ignore_case:
            flags |= re.IGNORECASE
        if self.regex_multiline:
            flags |= re.MULTILINE
        if self.regex_dot_matches_newline:
            flags |= re.DOTALL
        return flags


@dataclass
class MatchInfo:
    """1 件のマッチ情報を保持するデータクラス。

    Attributes:
        text: マッチが含まれるブロック全体のテキスト（コンテキスト）。
        matched_text: マッチした部分のみのテキスト。
        start: ブロックテキスト内のマッチ開始位置（0 始まり）。
        end: ブロックテキスト内のマッチ終了位置（end は非含）。
        block: マッチが含まれる :class:`ContentBlock`。
    """

    text: str
    matched_text: str
    start: int
    end: int
    block: ContentBlock

    def get_location_info(self) -> str:
        """マッチブロックの位置情報を文字列で返す。

        Returns:
            :meth:`ContentBlock.get_location_info` の結果。
        """
        return self.block.get_location_info()


@dataclass
class SearchResult:
    """1 ファイル分の検索結果を保持するデータクラス。

    Attributes:
        file_info: 検索対象ファイルの情報。
        matches: マッチ情報のリスト（最大 ``search_max_matches_per_file`` 件）。
        extracted_content: 抽出されたコンテンツ（プレビュー生成に使用）。
        error: エラーが発生した場合のメッセージ。
        truncated: マッチ件数が上限に達して打ち切られた場合 ``True``。
    """

    file_info: FileInfo
    matches: list[MatchInfo] = field(default_factory=list)
    extracted_content: ExtractedContent | None = None
    error: str | None = None
    truncated: bool = False

    @property
    def match_count(self) -> int:
        """実際のマッチ件数を返す。"""
        return len(self.matches)

    @property
    def display_count(self) -> str:
        """UI 表示用のマッチ件数文字列を返す。

        打ち切られた場合は ``"50>"`` のように上限値に ``>`` を付ける。
        """
        if self.truncated:
            return "50>"
        return str(self.match_count)


class Searcher:
    """ファイルリストを検索して :class:`SearchResult` を返すクラス。

    キャンセル操作（:meth:`cancel`）をサポートしており、
    長時間の検索を中断できる。
    """

    def __init__(self) -> None:
        self._logger = get_logger("search")
        self._config = get_config()
        self._cancelled = False

    def cancel(self) -> None:
        """進行中の検索をキャンセルする。"""
        self._cancelled = True

    def reset(self) -> None:
        """キャンセル状態をリセットする（次回呼び出し前に実行すること）。"""
        self._cancelled = False

    def search_files(
        self,
        files: list[FileInfo],
        options: SearchOptions,
        progress_callback: Callable[[int, int, int], None] | None = None,
    ) -> list[SearchResult]:
        """複数ファイルを一括検索する。

        Args:
            files: 検索対象ファイルのリスト。
            options: 検索オプション。
            progress_callback: 進捗コールバック
                ``(processed_bytes, total_bytes, file_count)`` を引数に取る。

        Returns:
            マッチまたはエラーが発生したファイルの :class:`SearchResult` リスト。
        """
        self._cancelled = False
        self._logger.set_correlation_id()

        total_bytes = sum(f.size for f in files)
        processed_bytes = 0
        results: list[SearchResult] = []
        start_time = time.time()

        self._logger.info(
            "start",
            f"Search started: '{options.query}'",
            file_count=len(files),
            total_bytes=total_bytes,
            use_regex=options.use_regex,
        )

        try:
            for file_idx, file_info in enumerate(files):
                if self._cancelled:
                    self._logger.info("cancel", "Search cancelled by user")
                    break

                result = self.search_file(file_info, options)
                if result.matches or result.error:
                    results.append(result)

                processed_bytes += file_info.size
                if progress_callback:
                    progress_callback(processed_bytes, total_bytes, file_idx + 1)

            elapsed_ms = int((time.time() - start_time) * 1000)
            self._logger.info(
                "end",
                f"Search completed: {len(results)} files matched",
                elapsed_ms=elapsed_ms,
                matched_files=len(results),
                total_matches=sum(r.match_count for r in results),
            )

        except Exception as exc:
            self._logger.exception("error", f"Search failed: {exc}", exc)
            raise

        finally:
            self._logger.clear_correlation_id()

        return results

    def search_file(
        self,
        file_info: FileInfo,
        options: SearchOptions,
    ) -> SearchResult:
        """1 ファイルを検索する。

        Extractor でコンテンツを抽出し、各 :class:`ContentBlock` を
        コンパイル済み正規表現で走査してマッチを収集する。

        Args:
            file_info: 検索対象ファイルの情報。
            options: 検索オプション。

        Returns:
            マッチ情報を含む :class:`SearchResult`。
        """
        result = SearchResult(file_info=file_info)
        max_matches = self._config.search_max_matches_per_file

        try:
            # キャッシュから取得を試み、無ければ抽出してキャッシュに格納
            from src.extraction.cache import get_extraction_cache

            cache = get_extraction_cache()
            content = cache.get(file_info.path)

            if content is None:
                extractor = get_extractor(file_info.path)
                if extractor is None:
                    result.error = f"サポートされていない形式: {file_info.extension}"
                    return result
                content = extractor.extract(file_info.path)
                cache.put(file_info.path, content)

            result.extracted_content = content

            if content.error:
                result.error = content.error
                return result

            pattern = self._compile_pattern(options)
            if pattern is None:
                result.error = "無効な検索パターン"
                return result

            for block in content.blocks:
                if self._cancelled:
                    break
                if len(result.matches) >= max_matches:
                    result.truncated = True
                    break
                if self._contains_exclude_words(block.text, options.exclude_words):
                    continue

                for match in self._find_matches(block, pattern, options):
                    if len(result.matches) >= max_matches:
                        result.truncated = True
                        break
                    result.matches.append(match)

            if result.matches:
                self._logger.debug(
                    "match",
                    f"Found {len(result.matches)} matches",
                    file_path=str(file_info.path),
                    truncated=result.truncated,
                )

        except Exception as exc:
            result.error = str(exc)
            self._logger.exception(
                "error",
                f"Search failed for file: {file_info.path}",
                exc,
                file_path=str(file_info.path),
            )

        return result

    # ------------------------------------------------------------------
    # 内部ヘルパー
    # ------------------------------------------------------------------

    def _compile_pattern(self, options: SearchOptions) -> re.Pattern | None:
        """検索クエリを正規表現パターンにコンパイルする。

        通常検索では query を :func:`re.escape` してから使用する。
        コンパイルエラーが発生した場合は警告ログを残して ``None`` を返す。

        Args:
            options: 検索オプション。

        Returns:
            コンパイル済みの正規表現パターン。エラー時は ``None``。
        """
        try:
            if options.use_regex:
                return re.compile(options.query, options.get_regex_flags())

            escaped = re.escape(options.query)
            if options.match_whole:
                escaped = f"^{escaped}$"
            flags = 0 if options.case_sensitive else re.IGNORECASE
            return re.compile(escaped, flags)

        except re.error as exc:
            self._logger.warning(
                "error",
                f"Invalid regex pattern: {options.query}",
                exception_message=str(exc),
            )
            return None

    def _contains_exclude_words(self, text: str, exclude_words: list[str]) -> bool:
        """テキストに除外キーワードが含まれているかを確認する（大文字小文字無視）。

        Args:
            text: 確認対象のテキスト。
            exclude_words: 除外するキーワードのリスト。

        Returns:
            いずれかの除外キーワードが含まれていれば ``True``。
        """
        text_lower = text.lower()
        return any(word.lower() in text_lower for word in exclude_words)

    def _find_matches(
        self,
        block: ContentBlock,
        pattern: re.Pattern,
        options: SearchOptions,
    ) -> list[MatchInfo]:
        """ブロックテキスト内の全マッチを検索して返す。

        ``match_whole=True`` かつ正規表現モードでない場合は、
        ブロック全体がクエリと一致するもののみを返す。

        Args:
            block: 検索対象のコンテンツブロック。
            pattern: コンパイル済み正規表現パターン。
            options: 検索オプション（``match_whole`` の確認に使用）。

        Returns:
            マッチした :class:`MatchInfo` のリスト。
        """
        matches: list[MatchInfo] = []
        for m in pattern.finditer(block.text):
            matched_text = m.group()
            if options.match_whole and not options.use_regex:
                if block.text.strip() != matched_text.strip():
                    continue
            matches.append(MatchInfo(
                text=block.text,
                matched_text=matched_text,
                start=m.start(),
                end=m.end(),
                block=block,
            ))
        return matches
