"""Search engine package."""

from .query_parser import FTS5QueryParser
from .synonyms import SynonymManager, DEFAULT_CARDIOLOGY_SYNONYMS, seed_default_synonyms
from .suggestions import SuggestionService
from .search_service import SearchService, SearchResultItem, SearchResponse

__all__ = [
    "FTS5QueryParser",
    "SynonymManager",
    "DEFAULT_CARDIOLOGY_SYNONYMS",
    "seed_default_synonyms",
    "SuggestionService",
    "SearchService",
    "SearchResultItem",
    "SearchResponse"
]
