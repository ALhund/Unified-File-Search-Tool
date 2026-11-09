"""検索モジュール"""

from src.search.query import CompiledQuery, QueryError, SearchOptions, split_terms
from src.search.searcher import (
    Searcher,
    SearchResult,
    SearchSummary,
    MatchInfo,
    load_content,
    search_content,
    shutdown_pool,
)

__all__ = [
    "CompiledQuery",
    "QueryError",
    "Searcher",
    "SearchOptions",
    "SearchResult",
    "SearchSummary",
    "MatchInfo",
    "load_content",
    "search_content",
    "shutdown_pool",
    "split_terms",
]
