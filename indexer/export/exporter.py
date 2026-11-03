"""Export manager for generating Full, Search-Only Compact, and Incremental update packages."""

from __future__ import annotations
import datetime
import hashlib
import os
import shutil
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, Callable

try:
    import zstandard as zstd
    ZSTD_AVAILABLE = True
except ImportError:
    zstd = None  # type: ignore
    ZSTD_AVAILABLE = False

from ..config import logger, DEFAULT_DB_PATH
from ..database.connection import DatabaseManager
from ..database.schema import create_schema
from .delta_package import IncrementalUpdatePackage
from ..extractors.base import calculate_sha256


class ExportType(str, Enum):
    FULL = "full"
    SEARCH_ONLY = "search_only"
    INCREMENTAL = "incremental"


@dataclass
class ExportResult:
    export_type: str
    output_path: Path
    uncompressed_size: int
    compressed_size: Optional[int]
    is_compressed: bool
    sha256_checksum: str
    total_documents: int
    total_paragraphs: int
    execution_time_ms: float

    @property
    def compression_ratio_str(self) -> str:
        if self.is_compressed and self.compressed_size and self.uncompressed_size > 0:
            reduction = (1.0 - (self.compressed_size / self.uncompressed_size)) * 100.0
            return f"{reduction:.1f}% reduction"
        return "Uncompressed"


def compress_file_zstd(
    src_path: Path,
    dest_path: Path,
    level: int = 10,
    chunk_size: int = 1024 * 1024,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> Tuple[int, str]:
    """
    Compress a file using Zstandard streaming compression.
    Returns (compressed_byte_size, sha256_of_compressed_file).
    """
    if not ZSTD_AVAILABLE:
        raise RuntimeError("zstandard is not installed. Please install it via: pip install zstandard")
    cctx = zstd.ZstdCompressor(level=level)
    hasher = hashlib.sha256()
    total_src_size = src_path.stat().st_size
    bytes_read = 0

    with open(src_path, "rb") as ifh, open(dest_path, "wb") as ofh:
        with cctx.stream_writer(ofh) as compressor:
            while chunk := ifh.read(chunk_size):
                compressor.write(chunk)
                bytes_read += len(chunk)
                if progress_callback:
                    progress_callback(bytes_read, total_src_size)

    # Compute sha256 of compressed output
    comp_size = dest_path.stat().st_size
    with open(dest_path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)

    return comp_size, hasher.hexdigest()


def decompress_file_zstd(
    src_path: Path,
    dest_path: Path,
    chunk_size: int = 1024 * 1024
) -> int:
    """Decompress a Zstandard archive back to destination file."""
    if not ZSTD_AVAILABLE:
        raise RuntimeError("zstandard is not installed. Please install it via: pip install zstandard")
    dctx = zstd.ZstdDecompressor()
    with open(src_path, "rb") as ifh, open(dest_path, "wb") as ofh:
        with dctx.stream_writer(ofh) as decompressor:
            while chunk := ifh.read(chunk_size):
                decompressor.write(chunk)
    return dest_path.stat().st_size


class ExportManager:
    """Generates portable SQLite search databases and delta packages with optional Zstandard compression."""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def get_database_size_preview(self) -> Dict[str, Any]:
        """Return actual disk size of database and stats before export."""
        stats = self.db.get_dashboard_stats()
        actual_db_size = self.db.get_database_file_size()

        conn = self.db.get_connection()
        total_paras = conn.execute("SELECT COUNT(*) FROM document_paragraphs").fetchone()[0]

        return {
            "actual_db_size": actual_db_size,
            "total_documents": stats.total_documents,
            "total_paragraphs": total_paras,
            "extracted_text_size": stats.extracted_text_size,
            "last_indexed": stats.last_indexing_date
        }

    def export_full_database(
        self,
        dest_path: Path | str,
        compress: bool = False,
        compression_level: int = 10,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> ExportResult:
        """
        Export a full clone of the database using VACUUM INTO.
        Guarantees a clean, unfragmented SQLite database file without locking transactions.
        """
        t0 = time.perf_counter()
        target = Path(dest_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)

        conn = self.db.get_connection()
        total_docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        total_paras = conn.execute("SELECT COUNT(*) FROM document_paragraphs").fetchone()[0]

        with tempfile.TemporaryDirectory(prefix="export_full_") as tmp_dir:
            temp_db = Path(tmp_dir) / "full_export.db"
            logger.info(f"Creating clean full database vacuum snapshot at {temp_db}...")
            # VACUUM INTO produces a pristine single-file copy
            conn.execute(f"VACUUM INTO '{temp_db}'")

            uncompressed_size = temp_db.stat().st_size

            if compress:
                final_path = target if target.suffix.lower() == ".zst" else target.with_suffix(target.suffix + ".zst")
                logger.info(f"Compressing database with Zstandard (level {compression_level}) to {final_path}...")
                comp_size, sha256_hash = compress_file_zstd(
                    temp_db, final_path, level=compression_level, progress_callback=progress_callback
                )
                output_path = final_path
                compressed_size = comp_size
                is_comp = True
            else:
                final_path = target if target.suffix.lower() != ".zst" else target.with_suffix("")
                shutil.copy2(str(temp_db), str(final_path))
                sha256_hash = calculate_sha256(final_path)
                output_path = final_path
                compressed_size = None
                is_comp = False

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return ExportResult(
            export_type=ExportType.FULL.value,
            output_path=output_path,
            uncompressed_size=uncompressed_size,
            compressed_size=compressed_size,
            is_compressed=is_comp,
            sha256_checksum=sha256_hash,
            total_documents=total_docs,
            total_paragraphs=total_paras,
            execution_time_ms=round(elapsed_ms, 2)
        )

    def export_search_only_database(
        self,
        dest_path: Path | str,
        compress: bool = False,
        compression_level: int = 10,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> ExportResult:
        """
        Create a compact portable search database for mobile PWA consumption.
        Contains:
          - Valid document metadata and links (excluding errors/unsupported)
          - Extracted pages and paragraphs
          - Collections
          - Full-text search index (FTS5) with merged b-tree segments (optimized)
          - Synonyms dictionary
          - Autocomplete vocabulary table
        """
        t0 = time.perf_counter()
        target = Path(dest_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)

        src_conn = self.db.get_connection()

        with tempfile.TemporaryDirectory(prefix="export_search_") as tmp_dir:
            temp_db = Path(tmp_dir) / "search_compact.db"
            dest_conn = sqlite3.connect(str(temp_db))
            dest_conn.execute("PRAGMA page_size = 4096;")
            dest_conn.execute("PRAGMA journal_mode = DELETE;")

            create_schema(dest_conn)

            logger.info("Transferring documents to search-only compact database...")
            # 1. Documents (excluding failed ones)
            docs = src_conn.execute(
                """
                SELECT document_id, filename, extension, file_size, modified_time,
                       sha256, source_path, google_drive_file_id, google_drive_url,
                       page_count, extraction_status, last_indexed
                FROM documents
                WHERE extraction_status != 'error'
                """
            ).fetchall()

            dest_conn.executemany(
                """
                INSERT INTO documents (
                    document_id, filename, extension, file_size, modified_time,
                    sha256, source_path, google_drive_file_id, google_drive_url,
                    page_count, extraction_status, last_indexed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [tuple(r) for r in docs]
            )
            valid_doc_ids = {r["document_id"] for r in docs}

            # 2. Document Pages
            pages = src_conn.execute(
                "SELECT page_id, document_id, page_number, extracted_text FROM document_pages"
            ).fetchall()
            valid_pages = [tuple(r) for r in pages if r["document_id"] in valid_doc_ids]
            dest_conn.executemany(
                "INSERT INTO document_pages (page_id, document_id, page_number, extracted_text) VALUES (?, ?, ?, ?)",
                valid_pages
            )

            # 3. Document Paragraphs
            paras = src_conn.execute(
                "SELECT paragraph_id, document_id, page_number, paragraph_number, paragraph_text FROM document_paragraphs"
            ).fetchall()
            valid_paras = [tuple(r) for r in paras if r["document_id"] in valid_doc_ids]
            dest_conn.executemany(
                """
                INSERT INTO document_paragraphs (
                    paragraph_id, document_id, page_number, paragraph_number, paragraph_text
                ) VALUES (?, ?, ?, ?, ?)
                """,
                valid_paras
            )

            # 4. Collections
            cols = src_conn.execute("SELECT collection_id, collection_name, description FROM collections").fetchall()
            dest_conn.executemany(
                "INSERT INTO collections (collection_id, collection_name, description) VALUES (?, ?, ?)",
                [tuple(r) for r in cols]
            )

            doc_cols = src_conn.execute("SELECT document_id, collection_id FROM document_collections").fetchall()
            dest_conn.executemany(
                "INSERT INTO document_collections (document_id, collection_id) VALUES (?, ?)",
                [tuple(r) for r in doc_cols if r["document_id"] in valid_doc_ids]
            )

            # 5. Synonyms
            syns = src_conn.execute("SELECT synonym_id, term, expansion, category, enabled FROM synonyms").fetchall()
            dest_conn.executemany(
                "INSERT INTO synonyms (synonym_id, term, expansion, category, enabled) VALUES (?, ?, ?, ?, ?)",
                [tuple(r) for r in syns]
            )

            # 6. FTS5 Search Index
            logger.info("Populating FTS5 search index in compact database...")
            fts_rows = src_conn.execute(
                "SELECT title, paragraph_text, page_text, document_id, page_number, paragraph_number FROM search_index"
            ).fetchall()
            valid_fts = [tuple(r) for r in fts_rows if r["document_id"] in valid_doc_ids]
            dest_conn.executemany(
                """
                INSERT INTO search_index (
                    title, paragraph_text, page_text, document_id, page_number, paragraph_number
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                valid_fts
            )

            # 7. Optimize FTS5 index (merges segments into a single compact tree)
            logger.info("Optimizing FTS5 virtual table segments...")
            dest_conn.execute("INSERT INTO search_index(search_index) VALUES('optimize');")
            dest_conn.commit()

            # 8. VACUUM to eliminate unallocated pages
            dest_conn.execute("VACUUM;")
            dest_conn.close()

            uncompressed_size = temp_db.stat_size if hasattr(temp_db, "stat_size") else temp_db.stat().st_size

            # 9. Optional Zstandard compression
            if compress:
                final_path = target if target.suffix.lower() == ".zst" else target.with_suffix(target.suffix + ".zst")
                logger.info(f"Compressing search-only database with Zstandard (level {compression_level}) to {final_path}...")
                comp_size, sha256_hash = compress_file_zstd(
                    temp_db, final_path, level=compression_level, progress_callback=progress_callback
                )
                output_path = final_path
                compressed_size = comp_size
                is_comp = True
            else:
                final_path = target if target.suffix.lower() != ".zst" else target.with_suffix("")
                shutil.copy2(str(temp_db), str(final_path))
                sha256_hash = calculate_sha256(final_path)
                output_path = final_path
                compressed_size = None
                is_comp = False

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return ExportResult(
            export_type=ExportType.SEARCH_ONLY.value,
            output_path=output_path,
            uncompressed_size=uncompressed_size,
            compressed_size=compressed_size,
            is_compressed=is_comp,
            sha256_checksum=sha256_hash,
            total_documents=len(docs),
            total_paragraphs=len(valid_paras),
            execution_time_ms=round(elapsed_ms, 2)
        )

    def export_incremental_package(
        self,
        dest_path: Path | str,
        since_date: str,
        compress: bool = False,
        compression_level: int = 10
    ) -> ExportResult:
        """
        Export changed documents, pages, and paragraphs since baseline date into a lightweight JSON package.
        """
        t0 = time.perf_counter()
        target = Path(dest_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)

        src_conn = self.db.get_connection()

        # Query modified documents
        doc_rows = src_conn.execute(
            """
            SELECT * FROM documents
            WHERE last_indexed >= ? AND extraction_status != 'error'
            ORDER BY document_id ASC
            """,
            (since_date,)
        ).fetchall()
        docs = [dict(r) for r in doc_rows]
        doc_ids = [d["document_id"] for d in docs]

        # Query pages
        pages = []
        if doc_ids:
            placeholders = ",".join(["?"] * len(doc_ids))
            page_rows = src_conn.execute(
                f"SELECT * FROM document_pages WHERE document_id IN ({placeholders})",
                doc_ids
            ).fetchall()
            pages = [dict(r) for r in page_rows]

        # Query paragraphs
        paras = []
        if doc_ids:
            placeholders = ",".join(["?"] * len(doc_ids))
            para_rows = src_conn.execute(
                f"SELECT * FROM document_paragraphs WHERE document_id IN ({placeholders})",
                doc_ids
            ).fetchall()
            paras = [dict(r) for r in para_rows]

        # Active synonyms
        syns = [dict(r) for r in src_conn.execute("SELECT * FROM synonyms WHERE enabled = 1").fetchall()]

        pkg = IncrementalUpdatePackage(
            created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            since_date=since_date,
            total_documents=len(docs),
            total_paragraphs=len(paras),
            documents=docs,
            pages=pages,
            paragraphs=paras,
            deleted_source_paths=[],
            synonyms=syns
        )

        with tempfile.TemporaryDirectory(prefix="export_delta_") as tmp_dir:
            temp_json = Path(tmp_dir) / "delta.json"
            json_str = pkg.to_json(indent=2)
            temp_json.write_text(json_str, encoding="utf-8")
            uncompressed_size = temp_json.stat().st_size

            if compress:
                final_path = target if target.suffix.lower() == ".zst" else target.with_suffix(target.suffix + ".zst")
                comp_size, sha256_hash = compress_file_zstd(temp_json, final_path, level=compression_level)
                output_path = final_path
                compressed_size = comp_size
                is_comp = True
            else:
                final_path = target if target.suffix.lower() != ".zst" else target.with_suffix("")
                shutil.copy2(str(temp_json), str(final_path))
                sha256_hash = calculate_sha256(final_path)
                output_path = final_path
                compressed_size = None
                is_comp = False

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return ExportResult(
            export_type=ExportType.INCREMENTAL.value,
            output_path=output_path,
            uncompressed_size=uncompressed_size,
            compressed_size=compressed_size,
            is_compressed=is_comp,
            sha256_checksum=sha256_hash,
            total_documents=len(docs),
            total_paragraphs=len(paras),
            execution_time_ms=round(elapsed_ms, 2)
        )
