"""Command Line Interface for headless indexing, scanning, and stats reporting."""

from __future__ import annotations
import argparse
import sys
from pathlib import Path
from typing import List

from .config import logger, DEFAULT_DB_PATH, find_libreoffice_binary, find_tesseract_binary
from .database.connection import DatabaseManager
from .engine.indexer_engine import IndexerEngine
from .ui.dashboard_widget import format_bytes


def print_stats(db_path: Path | str = DEFAULT_DB_PATH) -> None:
    """Print the 8 required dashboard metrics in a clean CLI table."""
    db = DatabaseManager(db_path)
    stats = db.get_dashboard_stats()

    print("\n" + "=" * 60)
    print("      MEDICAL LITERATURE SEARCH — INDEXER DASHBOARD")
    print("=" * 60)
    print(f"  1. Total Indexed Documents:   {stats.total_documents:,}")
    print(f"  2. Total Original File Size:  {format_bytes(stats.total_original_file_size)}")
    print(f"  3. Extracted Text Size:       {format_bytes(stats.extracted_text_size)}")
    print(f"  4. Search Database Size:      {format_bytes(stats.database_size)}")
    print(f"  5. Number of PDF Pages:       {stats.number_of_pdf_pages:,}")
    print(f"  6. Number of Word Documents:  {stats.number_of_word_documents:,}")
    print(f"  7. Number of Scanned PDFs:    {stats.number_of_scanned_pdfs:,}")
    print(f"  8. Last Indexing Date:        {stats.last_indexing_date or 'Never'}")
    print("=" * 60)

    # Also display dependency status
    lo_bin = find_libreoffice_binary()
    tess_bin = find_tesseract_binary()
    print(f"  LibreOffice:   {'Found (' + lo_bin + ')' if lo_bin else 'NOT FOUND'}")
    print(f"  Tesseract OCR: {'Found (' + tess_bin + ')' if tess_bin else 'NOT FOUND'}")
    print(f"  Database Path: {Path(db_path).resolve()}")
    print("=" * 60 + "\n")


def run_cli_indexing(folders: List[Path], db_path: Path | str = DEFAULT_DB_PATH) -> None:
    """Execute scanning and indexing in CLI mode with terminal logging."""
    print_stats(db_path)
    db = DatabaseManager(db_path)
    engine = IndexerEngine(db_manager=db)

    def on_progress(cur: int, tot: int, filename: str, msg: str) -> None:
        if tot > 0:
            pct = (cur / tot) * 100.0
            print(f"\r[{pct:5.1f}%] ({cur}/{tot}) {msg[:70]:<70}", end="", flush=True)
        else:
            print(f"\r{msg}", end="", flush=True)

    def on_error(path: str, err: str) -> None:
        print(f"\n[ERROR] {Path(path).name}: {err}")

    engine.on_progress = on_progress
    engine.on_error = on_error

    print(f"Starting indexing for {len(folders)} folder(s)...")
    res = engine.index_folders(folders)
    print("\n")
    print_stats(db_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Medical Literature Search Indexer CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Scan command
    scan_p = subparsers.add_parser("scan", help="Scan and index one or more directories")
    scan_p.add_argument("folders", nargs="+", help="Folders to scan and index")
    scan_p.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to SQLite database")

    # Stats command
    stats_p = subparsers.add_parser("stats", help="Display dashboard statistics")
    stats_p.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to SQLite database")

    # Retry command
    retry_p = subparsers.add_parser("retry", help="Retry failed documents")
    retry_p.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to SQLite database")

    # Clear command
    clear_p = subparsers.add_parser("clear", help="Reset/clear the entire search database")
    clear_p.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to SQLite database")

    args = parser.parse_args()

    if args.command == "stats":
        print_stats(args.db)
    elif args.command == "scan":
        folder_paths = [Path(f) for f in args.folders]
        run_cli_indexing(folder_paths, args.db)
    elif args.command == "retry":
        db = DatabaseManager(args.db)
        engine = IndexerEngine(db_manager=db)
        succeeded = engine.retry_failed_documents()
        print(f"Successfully re-indexed {succeeded} documents.")
        print_stats(args.db)
    elif args.command == "clear":
        db = DatabaseManager(args.db)
        db.clear_database()
        print("Database wiped successfully.")
        print_stats(args.db)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
