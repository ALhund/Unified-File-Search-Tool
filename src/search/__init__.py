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
    warm_pool,
    worker_count,
    logical_processors,
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
    "warm_pool",
    "worker_count",
    "logical_processors",
    "split_terms",
]
