"""SQLite Database connection and operational manager."""

from __future__ import annotations
import os
import sqlite3
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from ..models import ExtractedDocument, DashboardStats, ExtractionStatus
from .schema import create_schema
from ..search.synonyms import seed_default_synonyms
from ..config import logger, DEFAULT_DB_PATH


class DatabaseManager:
    """Thread-safe SQLite database manager for indexing and queries."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._lock = threading.Lock()
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        """Return a thread-local SQLite connection configured with WAL and foreign keys."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(
                str(self.db_path),
                timeout=60.0,
                check_same_thread=False
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA busy_timeout = 60000;")
            self._local.conn = conn
        return self._local.conn

    def init_db(self) -> None:
        """Initialize the database schema and default seed data."""
        with self._lock:
            conn = self.get_connection()
            create_schema(conn)
            seed_default_synonyms(conn)

    def close(self) -> None:
        """Close connection for current thread."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            try:
                self._local.conn.close()
            except Exception:
                pass
            self._local.conn = None

    def get_database_file_size(self) -> int:
        """Return total size of database file + WAL and SHM files on disk."""
        total = 0
        for suffix in ["", "-wal", "-shm"]:
            p = self.db_path.parent / (self.db_path.name + suffix)
            if p.exists():
                total += p.stat().st_size
        return total

    def save_document(self, doc: ExtractedDocument) -> int:
        """Insert or update extracted document, pages, paragraphs, and FTS5 index in a single transaction."""
        conn = self.get_connection()
        with self._lock:
            with conn:
                # Check if document already exists by source_path
                existing = conn.execute(
                    "SELECT document_id FROM documents WHERE source_path = ?",
                    (doc.source_path,)
                ).fetchone()

                if existing:
                    doc_id = existing["document_id"]
                    # Delete old pages, paragraphs, and FTS entries
                    conn.execute("DELETE FROM document_pages WHERE document_id = ?", (doc_id,))
                    conn.execute("DELETE FROM document_paragraphs WHERE document_id = ?", (doc_id,))
                    conn.execute("DELETE FROM search_index WHERE document_id = ?", (doc_id,))

                    # Update document metadata
                    conn.execute(
                        """
                        UPDATE documents SET
                            filename = ?,
                            extension = ?,
                            file_size = ?,
                            modified_time = ?,
                            sha256 = ?,
                            google_drive_file_id = ?,
                            google_drive_url = ?,
                            page_count = ?,
                            extraction_status = ?,
                            error_message = ?,
                            last_indexed = CURRENT_TIMESTAMP
                        WHERE document_id = ?
                        """,
                        (
                            doc.filename,
                            doc.extension.lower(),
                            doc.file_size,
                            doc.modified_time,
                            doc.sha256,
                            doc.google_drive_file_id,
                            doc.google_drive_url,
                            doc.page_count,
                            doc.extraction_status,
                            doc.error_message,
                            doc_id
                        )
                    )
                else:
                    cur = conn.execute(
                        """
                        INSERT INTO documents (
                            filename, extension, file_size, modified_time, sha256,
                            source_path, google_drive_file_id, google_drive_url,
                            page_count, extraction_status, error_message, last_indexed
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        """,
                        (
                            doc.filename,
                            doc.extension.lower(),
                            doc.file_size,
                            doc.modified_time,
                            doc.sha256,
                            doc.source_path,
                            doc.google_drive_file_id,
                            doc.google_drive_url,
                            doc.page_count,
                            doc.extraction_status,
                            doc.error_message,
                        )
                    )
                    doc_id = cur.lastrowid

                # If status is error, we stop here (metadata recorded for retry)
                if doc.extraction_status == ExtractionStatus.ERROR.value:
                    return doc_id

                # Insert pages
                if doc.pages:
                    conn.executemany(
                        """
                        INSERT INTO document_pages (document_id, page_number, extracted_text)
                        VALUES (?, ?, ?)
                        """,
                        [(doc_id, p.page_number, p.text) for p in doc.pages]
                    )

                # Insert paragraphs
                if doc.paragraphs:
                    conn.executemany(
                        """
                        INSERT INTO document_paragraphs (document_id, page_number, paragraph_number, paragraph_text)
                        VALUES (?, ?, ?, ?)
                        """,
                        [(doc_id, p.page_number, p.paragraph_number, p.text) for p in doc.paragraphs]
                    )

                # Insert into FTS5 search index
                # We index each paragraph along with document title and page context
                fts_records = []
                title = doc.title or Path(doc.filename).stem

                if doc.paragraphs:
                    for p in doc.paragraphs:
                        # Find corresponding page text for additional context if needed
                        page_text = ""
                        for pg in doc.pages:
                            if pg.page_number == p.page_number:
                                page_text = pg.text
                                break

                        fts_records.append((
                            title,
                            p.text,
                            page_text,
                            doc_id,
                            p.page_number,
                            p.paragraph_number
                        ))
                elif doc.pages:
                    # Fallback to page-level indexing if no paragraphs
                    for pg in doc.pages:
                        fts_records.append((
                            title,
                            pg.text,
                            pg.text,
                            doc_id,
                            pg.page_number,
                            1
                        ))

                if fts_records:
                    conn.executemany(
                        """
                        INSERT INTO search_index (
                            title, paragraph_text, page_text, document_id, page_number, paragraph_number
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        fts_records
                    )

                return doc_id

    def get_document_by_path(self, source_path: str) -> Optional[dict]:
        """Fetch document row by source path."""
        conn = self.get_connection()
        row = conn.execute("SELECT * FROM documents WHERE source_path = ?", (source_path,)).fetchone()
        return dict(row) if row else None

    def get_all_indexed_paths(self) -> Dict[str, Tuple[float, int, str]]:
        """Return map of source_path -> (modified_time, file_size, sha256) for all indexed documents."""
        conn = self.get_connection()
        rows = conn.execute(
            "SELECT source_path, modified_time, file_size, sha256 FROM documents"
        ).fetchall()
        return {r["source_path"]: (r["modified_time"], r["file_size"], r["sha256"]) for r in rows}

    def delete_document_by_path(self, source_path: str) -> bool:
        """Delete document and its related pages, paragraphs, and FTS5 entries."""
        conn = self.get_connection()
        with self._lock:
            with conn:
                row = conn.execute("SELECT document_id FROM documents WHERE source_path = ?", (source_path,)).fetchone()
                if not row:
                    return False
                doc_id = row["document_id"]
                conn.execute("DELETE FROM search_index WHERE document_id = ?", (doc_id,))
                conn.execute("DELETE FROM document_paragraphs WHERE document_id = ?", (doc_id,))
                conn.execute("DELETE FROM document_pages WHERE document_id = ?", (doc_id,))
                conn.execute("DELETE FROM document_collections WHERE document_id = ?", (doc_id,))
                conn.execute("DELETE FROM documents WHERE document_id = ?", (doc_id,))
                return True

    def get_failed_documents(self) -> List[dict]:
        """Return list of documents that encountered errors during extraction."""
        conn = self.get_connection()
        rows = conn.execute(
            "SELECT * FROM documents WHERE extraction_status = ?",
            (ExtractionStatus.ERROR.value,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_dashboard_stats(self) -> DashboardStats:
        """Query and return aggregated dashboard statistics."""
        conn = self.get_connection()

        # Total valid indexed documents
        row_docs = conn.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(file_size), 0) as total_size FROM documents WHERE extraction_status != ?",
            (ExtractionStatus.ERROR.value,)
        ).fetchone()
        total_docs = row_docs["cnt"] if row_docs else 0
        total_size = row_docs["total_size"] if row_docs else 0

        # Total extracted text size in bytes
        row_text = conn.execute(
            "SELECT COALESCE(SUM(LENGTH(extracted_text)), 0) as text_size FROM document_pages"
        ).fetchone()
        extracted_text_size = row_text["text_size"] if row_text else 0

        # Number of PDF pages
        row_pdf_pages = conn.execute(
            "SELECT COALESCE(SUM(page_count), 0) as pages FROM documents WHERE extension = '.pdf' AND extraction_status != ?",
            (ExtractionStatus.ERROR.value,)
        ).fetchone()
        pdf_pages = row_pdf_pages["pages"] if row_pdf_pages else 0

        # Word documents count (.docx and .doc)
        row_word = conn.execute(
            "SELECT COUNT(*) as cnt FROM documents WHERE extension IN ('.docx', '.doc') AND extraction_status != ?",
            (ExtractionStatus.ERROR.value,)
        ).fetchone()
        word_count = row_word["cnt"] if row_word else 0

        # Scanned PDFs count (scanned_ocr or mixed)
        row_scanned = conn.execute(
            "SELECT COUNT(*) as cnt FROM documents WHERE extension = '.pdf' AND extraction_status IN (?, ?)",
            (ExtractionStatus.SCANNED_OCR.value, ExtractionStatus.MIXED.value)
        ).fetchone()
        scanned_count = row_scanned["cnt"] if row_scanned else 0

        # Last indexing date
        row_last = conn.execute("SELECT MAX(last_indexed) as last_date FROM documents").fetchone()
        last_date = row_last["last_date"] if row_last and row_last["last_date"] else None

        db_file_size = self.get_database_file_size()

        return DashboardStats(
            total_documents=total_docs,
            total_original_file_size=total_size,
            extracted_text_size=extracted_text_size,
            database_size=db_file_size,
            number_of_pdf_pages=pdf_pages,
            number_of_word_documents=word_count,
            number_of_scanned_pdfs=scanned_count,
            indexing_progress=100.0 if total_docs > 0 else 0.0,
            last_indexing_date=last_date,
        )

    def clear_database(self) -> None:
        """Reset and wipe all data in the database."""
        conn = self.get_connection()
        with self._lock:
            with conn:
                conn.execute("DELETE FROM search_index")
                conn.execute("DELETE FROM document_paragraphs")
                conn.execute("DELETE FROM document_pages")
                conn.execute("DELETE FROM document_collections")
                conn.execute("DELETE FROM collections")
                conn.execute("DELETE FROM documents")
            conn.execute("VACUUM")

    def get_search_service(self):
        """Return a SearchService instance bound to current thread connection."""
        from ..search.search_service import SearchService
        return SearchService(self.get_connection())
