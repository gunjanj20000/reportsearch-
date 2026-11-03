"""Full-text search execution service with BM25 ranking, filters, snippets, and pagination."""

from __future__ import annotations
import time
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

from .query_parser import FTS5QueryParser
from .synonyms import SynonymManager
from .suggestions import SuggestionService
from ..config import logger


@dataclass
class SearchResultItem:
    document_id: int
    filename: str
    extension: str
    title: str
    page_number: int
    paragraph_number: int
    snippet: str
    rank_score: float
    file_size: int
    source_path: str
    google_drive_file_id: Optional[str] = None
    google_drive_url: Optional[str] = None
    last_indexed: Optional[str] = None


@dataclass
class SearchResponse:
    query: str
    parsed_fts_query: str
    expanded_query: Optional[str] = None
    synonyms_applied: List[Tuple[str, str]] = field(default_factory=list)
    total_count: int = 0
    page: int = 1
    page_size: int = 20
    total_pages: int = 0
    execution_time_ms: float = 0.0
    items: List[SearchResultItem] = field(default_factory=list)


class SearchService:
    """Core search execution service with BM25 ranking, snippet generation, and filtering."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.query_parser = FTS5QueryParser()
        self.synonym_manager = SynonymManager(self.conn)
        self.suggestion_service = SuggestionService(self.conn)

    def search(
        self,
        query: str,
        page: int = 1,
        page_size: int = 20,
        expand_synonyms: bool = False,
        extensions: Optional[List[str]] = None,
        title_only: bool = False,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        collection_id: Optional[int] = None
    ) -> SearchResponse:
        """
        Execute full-text search against SQLite FTS5 index.
        """
        start_time = time.perf_counter()
        clean_query = query.strip()

        if not clean_query:
            return SearchResponse(query=query, parsed_fts_query="", execution_time_ms=0.0)

        # 1. Synonym expansion (if enabled)
        expanded_query = None
        synonyms_applied: List[Tuple[str, str]] = []
        if expand_synonyms:
            expanded_query, synonyms_applied = self.synonym_manager.expand_query(clean_query)
            target_query = expanded_query
        else:
            target_query = clean_query

        # 2. Parse into valid FTS5 syntax
        parsed_fts = self.query_parser.parse(target_query)
        if not parsed_fts:
            return SearchResponse(query=query, parsed_fts_query="", execution_time_ms=0.0)

        # 3. Construct SQL query with BM25 ranking and filters
        where_clauses = ["s.search_index MATCH ?"]
        params: List[Any] = [parsed_fts]

        # Extension filter
        if extensions:
            ext_placeholders = ",".join(["?"] * len(extensions))
            where_clauses.append(f"d.extension IN ({ext_placeholders})")
            params.extend([ext.lower() for ext in extensions])

        # Date range filters
        if start_date:
            where_clauses.append("d.last_indexed >= ?")
            params.append(start_date)
        if end_date:
            where_clauses.append("d.last_indexed <= ?")
            params.append(end_date)

        # Collection filter
        join_clause = ""
        if collection_id:
            join_clause = "JOIN document_collections dc ON dc.document_id = d.document_id"
            where_clauses.append("dc.collection_id = ?")
            params.append(collection_id)

        where_sql = " AND ".join(where_clauses)

        # 4. Count total matches
        count_sql = f"""
            SELECT COUNT(*) as total
            FROM search_index s
            JOIN documents d ON d.document_id = s.document_id
            {join_clause}
            WHERE {where_sql}
        """
        try:
            total_count = self.conn.execute(count_sql, params).fetchone()["total"]
        except sqlite3.OperationalError as e:
            logger.warning(f"FTS5 count query syntax error on '{parsed_fts}': {e}")
            # Fallback to sanitized word phrase
            safe_query = f'"{clean_query}"'
            params[0] = safe_query
            parsed_fts = safe_query
            total_count = self.conn.execute(count_sql, params).fetchone()["total"]

        offset = max(0, (page - 1) * page_size)
        total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 0

        # 5. Fetch ranked results with BM25 and snippets
        # bm25 weights: title (5.0), paragraph_text (2.0), page_text (1.0)
        data_sql = f"""
            SELECT
                d.document_id,
                d.filename,
                d.extension,
                d.source_path,
                d.file_size,
                d.google_drive_file_id,
                d.google_drive_url,
                d.last_indexed,
                COALESCE(s.title, d.filename) as doc_title,
                s.page_number,
                s.paragraph_number,
                bm25(s.search_index, 5.0, 2.0, 1.0) as rank_score,
                snippet(s.search_index, -1, '<mark>', '</mark>', '...', 25) as snip
            FROM search_index s
            JOIN documents d ON d.document_id = s.document_id
            {join_clause}
            WHERE {where_sql}
            ORDER BY rank_score ASC
            LIMIT ? OFFSET ?
        """
        data_params = list(params) + [page_size, offset]
        rows = self.conn.execute(data_sql, data_params).fetchall()

        items = []
        for r in rows:
            items.append(SearchResultItem(
                document_id=r["document_id"],
                filename=r["filename"],
                extension=r["extension"],
                title=r["doc_title"],
                page_number=r["page_number"] or 1,
                paragraph_number=r["paragraph_number"] or 1,
                snippet=r["snip"],
                rank_score=round(r["rank_score"], 4),
                file_size=r["file_size"],
                source_path=r["source_path"],
                google_drive_file_id=r["google_drive_file_id"],
                google_drive_url=r["google_drive_url"],
                last_indexed=r["last_indexed"]
            ))

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        return SearchResponse(
            query=query,
            parsed_fts_query=parsed_fts,
            expanded_query=expanded_query,
            synonyms_applied=synonyms_applied,
            total_count=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            execution_time_ms=round(elapsed_ms, 2),
            items=items
        )

    def get_suggestions(self, prefix: str, limit: int = 8) -> List[Dict[str, Any]]:
        """Delegate to suggestion service."""
        return self.suggestion_service.get_suggestions(prefix, limit)
