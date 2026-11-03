"""Synonym Dictionary and Query Expansion Engine."""

from __future__ import annotations
import re
import sqlite3
from typing import Dict, List, Optional, Tuple


DEFAULT_CARDIOLOGY_SYNONYMS: Dict[str, str] = {}
DEFAULT_SYNONYMS: Dict[str, str] = {}


def seed_default_synonyms(conn: sqlite3.Connection) -> None:
    """No-op: database is kept clean for all-document search without forced cardiology presets."""
    pass


class SynonymManager:
    """Manages database-backed document synonyms, acronyms, and user extensions."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_all(self) -> List[dict]:
        """Fetch all synonyms with enabled state."""
        rows = self.conn.execute(
            "SELECT synonym_id, term, expansion, category, enabled FROM synonyms ORDER BY term ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_active_map(self) -> Dict[str, str]:
        """Return dict of term -> expansion for all enabled synonyms."""
        rows = self.conn.execute(
            "SELECT term, expansion FROM synonyms WHERE enabled = 1"
        ).fetchall()
        # Also map both ways (e.g. term -> expansion and expansion -> term)
        result = {}
        for r in rows:
            result[r["term"].upper()] = r["expansion"]
            result[r["expansion"].upper()] = r["term"]
        return result

    def add(self, term: str, expansion: str, category: str = "general") -> int:
        """Add a new custom synonym."""
        cur = self.conn.execute(
            "INSERT INTO synonyms (term, expansion, category, enabled) VALUES (?, ?, ?, 1)",
            (term.strip(), expansion.strip(), category.strip())
        )
        self.conn.commit()
        return cur.lastrowid

    def update(self, synonym_id: int, term: str, expansion: str, enabled: bool) -> bool:
        """Update existing synonym."""
        self.conn.execute(
            "UPDATE synonyms SET term = ?, expansion = ?, enabled = ? WHERE synonym_id = ?",
            (term.strip(), expansion.strip(), 1 if enabled else 0, synonym_id)
        )
        self.conn.commit()
        return True

    def delete(self, synonym_id: int) -> bool:
        """Remove synonym."""
        self.conn.execute("DELETE FROM synonyms WHERE synonym_id = ?", (synonym_id,))
        self.conn.commit()
        return True

    def expand_query(self, user_query: str) -> Tuple[str, List[Tuple[str, str]]]:
        """
        Optionally expand terms in user query using active synonym dictionary.
        Never silently replaces query; returns original query alongside expansion.
        """
        active_map = self.get_active_map()
        if not active_map:
            return user_query, []

        expansions_used: List[Tuple[str, str]] = []
        words = re.findall(r'(\"[^\"]+\"|\b\w+\b|[^\s\w\"])', user_query)

        expanded_parts = []
        i = 0
        while i < len(words):
            word = words[i]

            # Skip quoted phrases or operators
            if word.startswith('"') or word.upper() in {"AND", "OR", "NOT", "NEAR"}:
                expanded_parts.append(word)
                i += 1
                continue

            # Check multi-word synonym match first (e.g. "Left Main")
            matched_multi = False
            for lookahead in [3, 2]:
                if i + lookahead <= len(words):
                    candidate_multi = " ".join(words[i:i + lookahead]).upper()
                    if candidate_multi in active_map:
                        expansion = active_map[candidate_multi]
                        orig_phrase = " ".join(words[i:i + lookahead])
                        expanded_parts.append(f'("{orig_phrase}" OR "{expansion}")')
                        expansions_used.append((orig_phrase, expansion))
                        i += lookahead
                        matched_multi = True
                        break

            if matched_multi:
                continue

            # Single word match (e.g. "LM", "CTO", "IVUS")
            upper_word = word.upper()
            if upper_word in active_map:
                expansion = active_map[upper_word]
                expanded_parts.append(f'("{word}" OR "{expansion}")')
                expansions_used.append((word, expansion))
            else:
                expanded_parts.append(word)
            i += 1

        expanded_query_str = " ".join(expanded_parts)
        return expanded_query_str, expansions_used
