"""検索条件の解釈と照合

検索語（複数語のAND/OR、フレーズ、正規表現）を1つの正規表現にまとめ、
全角/半角・大文字/小文字を吸収した文字列に対して照合する。
"""

import re
from dataclasses import dataclass, field
from typing import Iterator

from src.common.textnorm import fold_query, fold_text


class QueryError(ValueError):
    """検索条件が不正"""


@dataclass
class SearchOptions:
    """検索オプション"""
    query: str
    use_regex: bool = False
    case_sensitive: bool = False
    ignore_width: bool = True  # 全角/半角を区別しない
    match_whole: bool = False  # セル・行・段落の全体が一致するものだけ
    term_mode: str = "and"  # and: すべて含む / or: いずれか含む / phrase: 入力どおり
    exclude_words: list[str] = field(default_factory=list)
    
    # 正規表現オプション
    regex_multiline: bool = False
    regex_dot_matches_newline: bool = False


def split_terms(query: str) -> list[str]:
    """空白区切りで語に分ける（"..." で囲むと空白を含む語にできる）"""
    terms: list[str] = []
    for quoted, bare in re.findall(r'"([^"]+)"|(\S+)', query.replace("　", " ")):
        term = quoted or bare
        if term and term not in terms:
            terms.append(term)
    return terms


class CompiledQuery:
    """コンパイル済みの検索条件"""
    
    def __init__(self, options: SearchOptions):
        self.options = options
        self.use_regex = options.use_regex
        self.ignore_width = options.ignore_width
        # 正規表現では大文字小文字の無視をフラグで行い、文字列側は変換しない
        self.fold_case = not options.case_sensitive and not options.use_regex
        self.match_whole = options.match_whole and not options.use_regex
        
        if not options.query.strip():
            raise QueryError("検索語を入力してください")
        
        if options.use_regex:
            flags = 0 if options.case_sensitive else re.IGNORECASE
            if options.regex_multiline:
                flags |= re.MULTILINE
            if options.regex_dot_matches_newline:
                flags |= re.DOTALL
            try:
                self.pattern = re.compile(options.query, flags)
            except re.error as e:
                raise QueryError(f"正規表現が正しくありません: {e}") from e
            self.terms = [options.query]
            self.require_all = False
        else:
            raw_terms = (
                [options.query.strip()] if options.term_mode == "phrase"
                else split_terms(options.query)
            )
            terms: list[str] = []
            for term in raw_terms:
                folded = fold_query(term, self.fold_case, self.ignore_width)
                if folded and folded not in terms:
                    terms.append(folded)
            if not terms:
                raise QueryError("検索語を入力してください")
            self.terms = terms
            self.require_all = options.term_mode == "and" and len(terms) > 1
            # 長い語を優先して照合する（「バナナ」と「バナナジュース」など）
            order = sorted(range(len(terms)), key=lambda i: -len(terms[i]))
            self.pattern = re.compile(
                "|".join(f"(?P<t{i}>{re.escape(terms[i])})" for i in order)
            )
        
        self._excludes = [
            folded
            for word in options.exclude_words
            if (folded := fold_query(word, True, self.ignore_width))
        ]
    
    @property
    def term_count(self) -> int:
        return len(self.terms)
    
    def is_excluded(self, text: str) -> bool:
        """除外語を含むか"""
        if not self._excludes:
            return False
        folded = fold_text(text, True, self.ignore_width).text
        return any(word in folded for word in self._excludes)
    
    def finditer(self, text: str) -> Iterator[tuple[int, int, int]]:
        """マッチを (開始, 終了, 語番号) で返す（位置は元の文字列基準）"""
        folded = fold_text(text, self.fold_case, self.ignore_width)
        
        if self.match_whole:
            stripped = folded.text.strip()
            for index, term in enumerate(self.terms):
                if stripped == term:
                    begin = folded.text.index(stripped) if stripped else 0
                    start, end = folded.span(begin, begin + len(stripped))
                    yield start, end, index
            return
        
        for m in self.pattern.finditer(folded.text):
            if m.end() == m.start():
                continue  # 空文字へのマッチ（.* など）は無視
            start, end = folded.span(m.start(), m.end())
            index = int(m.lastgroup[1:]) if not self.use_regex and m.lastgroup else 0
            yield start, end, index
