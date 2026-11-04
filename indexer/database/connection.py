"""SQLite Database connection and operational manager."""

from __future__ import annotations
import os
import sqlite3
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from ..models import ExtractedDocument, DashboardStats, ExtractionStatus
from .schema import create_schema
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
        """Initialize the database schema."""
        with self._lock:
            conn = self.get_connection()
            create_schema(conn)

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
                conn.execute("DELETE FROM indexed_folders")
            conn.execute("VACUUM")

        # Clean archive cache directory
        try:
            cache_dir = self.db_path.parent / "archive_cache"
            if cache_dir.exists():
                import shutil
                shutil.rmtree(cache_dir, ignore_errors=True)
                cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def get_indexed_folders(self) -> List[Dict[str, Any]]:
        """Retrieve all configured folders with live document counts."""
        conn = self.get_connection()
        rows = conn.execute(
            """
            SELECT 
                f.folder_id,
                f.folder_path,
                f.display_name,
                f.is_archive,
                f.added_at,
                f.last_scanned,
                f.document_count,
                f.status,
                (
                    SELECT COUNT(*) FROM documents d 
                    WHERE d.source_path = f.folder_path 
                       OR d.source_path LIKE f.folder_path || '/%' 
                       OR d.source_path LIKE f.folder_path || '\\%'
                       OR d.source_path LIKE f.folder_path || '#%'
                ) AS live_doc_count
            FROM indexed_folders f
            ORDER BY f.folder_id ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def add_indexed_folder(
        self, folder_path: str, display_name: Optional[str] = None, is_archive: bool = False
    ) -> Dict[str, Any]:
        """Add or update an indexed folder source."""
        clean_path = str(folder_path).strip()
        if not clean_path.startswith(("\\\\", "//", "smb://")):
            try:
                clean_path = str(Path(clean_path).resolve())
            except Exception:
                pass
        name = display_name or Path(clean_path).name or clean_path
        conn = self.get_connection()
        with self._lock:
            with conn:
                conn.execute(
                    """
                    INSERT INTO indexed_folders (folder_path, display_name, is_archive, added_at, status)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP, 'active')
                    ON CONFLICT(folder_path) DO UPDATE SET
                        display_name = excluded.display_name,
                        is_archive = excluded.is_archive,
                        status = 'active'
                    """,
                    (clean_path, name, 1 if is_archive else 0)
                )
                row = conn.execute("SELECT * FROM indexed_folders WHERE folder_path = ?", (clean_path,)).fetchone()
                return dict(row) if row else {}

    def remove_indexed_folder(self, folder_id: int, delete_documents: bool = False) -> bool:
        """Remove a folder from indexed_folders and optionally purge its indexed documents."""
        conn = self.get_connection()
        with self._lock:
            with conn:
                folder_row = conn.execute("SELECT folder_path FROM indexed_folders WHERE folder_id = ?", (folder_id,)).fetchone()
                if not folder_row:
                    return False
                folder_path = folder_row["folder_path"]
                if delete_documents:
                    doc_rows = conn.execute(
                        """
                        SELECT document_id FROM documents 
                        WHERE source_path = ? 
                           OR source_path LIKE ? || '/%' 
                           OR source_path LIKE ? || '\\%'
                           OR source_path LIKE ? || '#%'
                        """,
                        (folder_path, folder_path, folder_path, folder_path)
                    ).fetchall()
                    doc_ids = [r["document_id"] for r in doc_rows]
                    if doc_ids:
                        id_placeholders = ",".join("?" * len(doc_ids))
                        conn.execute(f"DELETE FROM search_index WHERE document_id IN ({id_placeholders})", doc_ids)
                        conn.execute(f"DELETE FROM document_paragraphs WHERE document_id IN ({id_placeholders})", doc_ids)
                        conn.execute(f"DELETE FROM document_pages WHERE document_id IN ({id_placeholders})", doc_ids)
                        conn.execute(f"DELETE FROM document_collections WHERE document_id IN ({id_placeholders})", doc_ids)
                        conn.execute(f"DELETE FROM documents WHERE document_id IN ({id_placeholders})", doc_ids)
                conn.execute("DELETE FROM indexed_folders WHERE folder_id = ?", (folder_id,))
                return True

    def update_folder_scan_stats(self, folder_path: str, doc_count: Optional[int] = None) -> None:
        """Update last_scanned timestamp and document_count for an indexed folder."""
        clean_path = str(folder_path).strip()
        conn = self.get_connection()
        with self._lock:
            with conn:
                if doc_count is not None:
                    conn.execute(
                        "UPDATE indexed_folders SET last_scanned = CURRENT_TIMESTAMP, document_count = ? WHERE folder_path = ?",
                        (doc_count, clean_path)
                    )
                else:
                    conn.execute(
                        """
                        UPDATE indexed_folders SET 
                            last_scanned = CURRENT_TIMESTAMP,
                            document_count = (
                                SELECT COUNT(*) FROM documents d 
                                WHERE d.source_path = indexed_folders.folder_path 
                                   OR d.source_path LIKE indexed_folders.folder_path || '/%' 
                                   OR d.source_path LIKE indexed_folders.folder_path || '\\%'
                                   OR d.source_path LIKE indexed_folders.folder_path || '#%'
                            )
                        WHERE folder_path = ?
                        """,
                        (clean_path,)
                    )

    def get_search_service(self):
        """Return a SearchService instance bound to current thread connection."""
        from ..search.search_service import SearchService
        return SearchService(self.get_connection())
