"""Robust FTS5 Query Parser and Sanitizer supporting Phrase, Boolean, Prefix, and Exclusion."""

from __future__ import annotations
import re
from typing import List, Tuple


class FTS5QueryParser:
    """Parses and sanitizes user search input into valid SQLite FTS5 query strings."""

    @staticmethod
    def parse(user_input: str) -> str:
        """
        Convert user input into safe FTS5 query syntax.
        Supports:
          - Phrase search: "left main"
          - Boolean search: AND, OR, NOT
          - Exclusion terms: -thrombosis or NOT thrombosis
          - Prefix search: litho*
          - Implicit AND between terms
        """
        text = user_input.strip()
        if not text:
            return ""

        # Balance unclosed double quotes
        quote_count = text.count('"')
        if quote_count % 2 != 0:
            text += '"'

        # Tokenize by quoted phrases, words with optional prefix/asterisk, or operators
        token_pattern = re.compile(
            r'(-?\"[^\"]+\")|(\b(?:AND|OR|NOT)\b)|(-?\b[\w\u0900-\u097F]+(?:\*)?)|([^\s\w\"])',
            re.IGNORECASE
        )

        tokens: List[Tuple[str, str]] = []  # (type, value)

        for match in token_pattern.finditer(text):
            quoted, op, word, punct = match.groups()

            if quoted:
                is_neg = quoted.startswith("-")
                phrase_body = quoted[1:] if is_neg else quoted
                tokens.append(("NEG_PHRASE" if is_neg else "PHRASE", phrase_body))
            elif op:
                tokens.append(("OP", op.upper()))
            elif word:
                is_neg = word.startswith("-")
                clean_word = word[1:] if is_neg else word
                tokens.append(("NEG_WORD" if is_neg else "WORD", clean_word))
            elif punct and punct in ["*", "(", ")"]:
                tokens.append(("SPECIAL", punct))

        if not tokens:
            return ""

        # Assemble into valid FTS5 expression
        clauses: List[str] = []
        i = 0
        while i < len(tokens):
            ttype, tval = tokens[i]

            if ttype == "PHRASE":
                clauses.append(tval)
            elif ttype == "WORD":
                clauses.append(tval)
            elif ttype == "NEG_WORD":
                if clauses:
                    clauses.append(f"NOT {tval}")
                else:
                    # FTS5 cannot start with NOT without a positive term; ignore leading NOT
                    pass
            elif ttype == "NEG_PHRASE":
                if clauses:
                    clauses.append(f"NOT {tval}")
                else:
                    pass
            elif ttype == "OP":
                # Ensure binary operator has terms on both sides
                if clauses and i + 1 < len(tokens) and tokens[i + 1][0] not in ["OP"]:
                    clauses.append(tval)
            elif ttype == "SPECIAL":
                if tval in ["(", ")"]:
                    clauses.append(tval)
            i += 1

        if not clauses:
            # Fallback to quoting raw alphanumeric tokens
            raw_words = re.findall(r'[\w\u0900-\u097F]+', user_input)
            return " AND ".join(f'"{w}"' for w in raw_words)

        # Merge adjacent non-operator terms with implicit AND
        result_parts: List[str] = []
        for idx, clause in enumerate(clauses):
            if idx > 0:
                prev = result_parts[-1]
                # If neither is an operator and neither is parenthesis, insert implicit AND
                if prev not in ["AND", "OR", "NOT", "("] and clause not in ["AND", "OR", "NOT", ")"]:
                    if not clause.startswith("NOT "):
                        result_parts.append("AND")
            result_parts.append(clause)

        return " ".join(result_parts)
