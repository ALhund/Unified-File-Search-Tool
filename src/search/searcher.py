"""検索モジュール

ファイル内容を検索し、マッチ箇所を返す。
"""

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from src.common.config import get_config
from src.common.logger import get_logger
from src.enumeration import FileInfo
from src.extraction import get_extractor, ExtractedContent, ContentBlock


@dataclass
class SearchOptions:
    """検索オプション"""
    query: str
    case_sensitive: bool = False
    use_regex: bool = False
    match_whole: bool = False  # 全文一致
    exclude_words: list[str] = field(default_factory=list)
    
    # 正規表現オプション（3つに固定）
    regex_ignore_case: bool = True
    regex_multiline: bool = False
    regex_dot_matches_newline: bool = False
    
    def get_regex_flags(self) -> int:
        """正規表現フラグを取得"""
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
    """マッチ情報"""
    text: str  # マッチしたテキスト（コンテキスト含む）
    matched_text: str  # マッチした部分のみ
    start: int  # マッチ開始位置
    end: int  # マッチ終了位置
    block: ContentBlock  # 元のContentBlock
    
    def get_location_info(self) -> str:
        """位置情報を文字列で取得"""
        return self.block.get_location_info()


@dataclass
class SearchResult:
    """検索結果（1ファイル分）"""
    file_info: FileInfo
    matches: list[MatchInfo] = field(default_factory=list)
    extracted_content: Optional[ExtractedContent] = None
    error: Optional[str] = None
    truncated: bool = False  # 50件で打ち切られたか
    
    @property
    def match_count(self) -> int:
        return len(self.matches)
    
    @property
    def display_count(self) -> str:
        """表示用のカウント（50超は '50>'）"""
        if self.truncated:
            return "50>"
        return str(self.match_count)


class Searcher:
    """検索クラス"""
    
    def __init__(self):
        self._logger = get_logger("search")
        self._config = get_config()
        self._cancelled = False
    
    def cancel(self) -> None:
        """検索をキャンセル"""
        self._cancelled = True
    
    def reset(self) -> None:
        """キャンセル状態をリセット"""
        self._cancelled = False
    
    def search_files(
        self,
        files: list[FileInfo],
        options: SearchOptions,
        progress_callback: Optional[Callable[[int, int, int], None]] = None,
    ) -> list[SearchResult]:
        """複数ファイルを検索
        
        Args:
            files: 検索対象ファイル一覧
            options: 検索オプション
            progress_callback: 進捗コールバック(processed_bytes, total_bytes, file_count)
        
        Returns:
            マッチしたファイルの検索結果一覧
        """
        self._cancelled = False
        correlation_id = self._logger.set_correlation_id()
        
        total_bytes = sum(f.size for f in files)
        processed_bytes = 0
        results: list[SearchResult] = []
        
        start_time = time.time()
        self._logger.info("start", f"Search started: '{options.query}'", extra={
            "file_count": len(files),
            "total_bytes": total_bytes,
            "use_regex": options.use_regex,
        })
        
        try:
            for file_idx, file_info in enumerate(files):
                if self._cancelled:
                    self._logger.info("cancel", "Search cancelled by user")
                    break
                
                # ファイルを検索
                result = self.search_file(file_info, options)
                
                # マッチがあれば結果に追加
                if result.matches or result.error:
                    results.append(result)
                
                # 進捗更新（ファイル単位で加算）
                processed_bytes += file_info.size
                if progress_callback:
                    progress_callback(processed_bytes, total_bytes, file_idx + 1)
            
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._logger.info("end", f"Search completed: {len(results)} files matched", extra={
                "matched_files": len(results),
                "total_matches": sum(r.match_count for r in results),
            }, elapsed_ms=elapsed_ms)
        
        except Exception as e:
            self._logger.exception("error", f"Search failed: {e}", e)
            raise
        
        finally:
            self._logger.clear_correlation_id()
        
        return results
    
    def search_file(
        self,
        file_info: FileInfo,
        options: SearchOptions,
    ) -> SearchResult:
        """1ファイルを検索
        
        Args:
            file_info: 検索対象ファイル
            options: 検索オプション
        
        Returns:
            検索結果
        """
        result = SearchResult(file_info=file_info)
        max_matches = self._config.search_max_matches_per_file
        
        try:
            # Extractorを取得
            extractor = get_extractor(file_info.path)
            if extractor is None:
                result.error = f"サポートされていない形式: {file_info.extension}"
                return result
            
            # テキスト抽出
            content = extractor.extract(file_info.path)
            result.extracted_content = content
            
            if content.error:
                result.error = content.error
                return result
            
            # 検索パターンを準備
            pattern = self._compile_pattern(options)
            if pattern is None:
                result.error = "無効な検索パターン"
                return result
            
            # 各ブロックを検索
            for block in content.blocks:
                if self._cancelled:
                    break
                
                if len(result.matches) >= max_matches:
                    result.truncated = True
                    break
                
                # 除外語チェック
                if self._contains_exclude_words(block.text, options.exclude_words):
                    continue
                
                # マッチを検索
                matches = self._find_matches(block, pattern, options)
                
                for match in matches:
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
        
        except Exception as e:
            result.error = str(e)
            self._logger.exception(
                "error",
                f"Search failed for file: {file_info.path}",
                e,
                file_path=str(file_info.path),
            )
        
        return result
    
    def _compile_pattern(self, options: SearchOptions) -> Optional[re.Pattern]:
        """検索パターンをコンパイル"""
        try:
            if options.use_regex:
                return re.compile(options.query, options.get_regex_flags())
            else:
                # 通常検索（正規表現エスケープ）
                escaped = re.escape(options.query)
                
                if options.match_whole:
                    # 全文一致
                    escaped = f"^{escaped}$"
                
                flags = 0 if options.case_sensitive else re.IGNORECASE
                return re.compile(escaped, flags)
        
        except re.error as e:
            self._logger.warning("error", f"Invalid regex pattern: {options.query}", exception_message=str(e))
            return None
    
    def _contains_exclude_words(self, text: str, exclude_words: list[str]) -> bool:
        """除外語が含まれているか"""
        text_lower = text.lower()
        for word in exclude_words:
            if word.lower() in text_lower:
                return True
        return False
    
    def _find_matches(
        self,
        block: ContentBlock,
        pattern: re.Pattern,
        options: SearchOptions,
    ) -> list[MatchInfo]:
        """ブロック内のマッチを検索"""
        matches = []
        
        for match in pattern.finditer(block.text):
            matched_text = match.group()
            
            # 全文一致モードの場合、ブロック全体と一致するか確認
            if options.match_whole and not options.use_regex:
                if block.text.strip() != matched_text.strip():
                    continue
            
            matches.append(MatchInfo(
                text=block.text,
                matched_text=matched_text,
                start=match.start(),
                end=match.end(),
                block=block,
            ))
        
        return matches
