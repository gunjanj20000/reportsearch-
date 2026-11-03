"""Search suggestions and auto-complete using FTS5 vocabulary and document titles."""

from __future__ import annotations
import sqlite3
from typing import List, Dict, Any


class SuggestionService:
    """Provides typeahead suggestions from vocabulary index, document titles, and cardiology acronyms."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_suggestions(self, prefix: str, limit: int = 8) -> List[Dict[str, Any]]:
        """
        Return ranked autocomplete suggestions for a given input prefix.
        Returns a list of dicts: {"type": "term"|"title"|"synonym", "text": str, "extra": str}
        """
        clean_prefix = prefix.strip().lower()
        if not clean_prefix or len(clean_prefix) < 2:
            return []

        suggestions: List[Dict[str, Any]] = []
        seen_texts = set()

        # 1. Cardiology Synonyms match
        try:
            syn_rows = self.conn.execute(
                """
                SELECT term, expansion FROM synonyms
                WHERE enabled = 1 AND (LOWER(term) LIKE ? OR LOWER(expansion) LIKE ?)
                LIMIT 3
                """,
                (f"{clean_prefix}%", f"%{clean_prefix}%")
            ).fetchall()

            for r in syn_rows:
                t, exp = r["term"], r["expansion"]
                label = f"{t} — {exp}"
                if label not in seen_texts:
                    seen_texts.add(label)
                    suggestions.append({
                        "type": "synonym",
                        "text": t,
                        "display": label,
                        "extra": exp
                    })
        except Exception:
            pass

        # 2. Vocabulary terms match from FTS5
        try:
            vocab_glob = f"{clean_prefix}*"
            vocab_rows = self.conn.execute(
                """
                SELECT term, cnt FROM search_vocab
                WHERE term GLOB ? AND LENGTH(term) > 2
                ORDER BY cnt DESC
                LIMIT ?
                """,
                (vocab_glob, limit)
            ).fetchall()

            for r in vocab_rows:
                term = r["term"]
                if term not in seen_texts:
                    seen_texts.add(term)
                    suggestions.append({
                        "type": "term",
                        "text": term,
                        "display": term,
                        "count": r["cnt"]
                    })
        except Exception:
            # Fallback if search_vocab has an issue
            pass

        # 3. Document Title match
        try:
            title_rows = self.conn.execute(
                """
                SELECT title, document_id FROM documents
                WHERE LOWER(title) LIKE ? AND extraction_status != 'error'
                LIMIT 3
                """,
                (f"%{clean_prefix}%",)
            ).fetchall()

            for r in title_rows:
                title = r["title"]
                if title not in seen_texts:
                    seen_texts.add(title)
                    suggestions.append({
                        "type": "title",
                        "text": f'"{title}"',
                        "display": f"📄 {title}",
                        "document_id": r["document_id"]
                    })
        except Exception:
            pass

        return suggestions[:limit]
