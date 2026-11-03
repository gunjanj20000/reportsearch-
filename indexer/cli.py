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

    # Search command (Phase 2)
    search_p = subparsers.add_parser("search", help="Execute FTS5 search query")
    search_p.add_argument("query", help="Search query string")
    search_p.add_argument("--synonyms", action="store_true", help="Enable cardiology synonym expansion")
    search_p.add_argument("--ext", nargs="+", help="Filter by extensions (e.g. .pdf .docx)")
    search_p.add_argument("--page", type=int, default=1, help="Page number")
    search_p.add_argument("--limit", type=int, default=10, help="Results per page")
    search_p.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to SQLite database")

    # Suggest command (Phase 2)
    suggest_p = subparsers.add_parser("suggest", help="Get autocomplete suggestions")
    suggest_p.add_argument("prefix", help="Term prefix to auto-complete")
    suggest_p.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to SQLite database")

    # Synonyms management command (Phase 2)
    syn_p = subparsers.add_parser("synonyms", help="View or add cardiology synonyms")
    syn_p.add_argument("--add", nargs=2, metavar=("TERM", "EXPANSION"), help="Add a custom synonym")
    syn_p.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to SQLite database")

    # Export command (Phase 3)
    export_p = subparsers.add_parser("export", help="Export portable database or incremental package")
    export_p.add_argument(
        "--type",
        choices=["search-only", "full", "incremental"],
        default="search-only",
        help="Export package type (default: search-only)"
    )
    export_p.add_argument("--output", "-o", required=True, help="Destination file path")
    export_p.add_argument("--compress", action="store_true", help="Enable Zstandard compression")
    export_p.add_argument("--level", type=int, default=10, help="Zstandard compression level (1-19)")
    export_p.add_argument("--since", help="Baseline timestamp for incremental update (ISO format)")
    export_p.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to SQLite database")

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
    elif args.command == "search":
        db = DatabaseManager(args.db)
        search_svc = db.get_search_service()
        res = search_svc.search(
            query=args.query,
            page=args.page,
            page_size=args.limit,
            expand_synonyms=args.synonyms,
            extensions=args.ext
        )
        print("\n" + "=" * 60)
        print(f"SEARCH RESULTS: {res.total_count} matches found in {res.execution_time_ms:.2f} ms")
        print(f"Query: {res.query!r}")
        print(f"Parsed FTS: {res.parsed_fts_query!r}")
        if res.expanded_query:
            print(f"Synonym Expansion: {res.expanded_query}")
            for t, exp in res.synonyms_applied:
                print(f"  → {t} expanded to: {exp}")
        print("=" * 60)

        for idx, item in enumerate(res.items, start=(res.page - 1) * res.page_size + 1):
            clean_snip = item.snippet.replace("<mark>", "\033[1;33m").replace("</mark>", "\033[0m")
            print(f"\n{idx}. [{item.extension.upper()}] {item.title}")
            print(f"   File: {item.filename} (Page {item.page_number}, Para {item.paragraph_number}) | BM25 Rank: {item.rank_score}")
            print(f"   Snippet: {clean_snip}")

        print(f"\nPage {res.page} of {res.total_pages} (Total: {res.total_count})\n")
    elif args.command == "suggest":
        db = DatabaseManager(args.db)
        search_svc = db.get_search_service()
        suggestions = search_svc.get_suggestions(args.prefix)
        print(f"\nAuto-complete suggestions for prefix '{args.prefix}':")
        for s in suggestions:
            print(f"  • [{s['type'].upper()}] {s['display']}")
        print()
    elif args.command == "synonyms":
        db = DatabaseManager(args.db)
        syn_mgr = db.get_search_service().synonym_manager
        if args.add:
            term, expansion = args.add
            syn_id = syn_mgr.add(term, expansion)
            print(f"Added synonym #{syn_id}: {term} → {expansion}")
        else:
            all_syns = syn_mgr.get_all()
            print(f"\nCardiology Synonym Dictionary ({len(all_syns)} terms):")
            print("-" * 50)
            for s in all_syns:
                status = "✓" if s["enabled"] else "✗"
                print(f"  [{status}] {s['term']:<8} → {s['expansion']}")
            print("-" * 50 + "\n")
    elif args.command == "export":
        from .export.exporter import ExportManager
        db = DatabaseManager(args.db)
        exp_mgr = ExportManager(db)

        # Print preview before export
        preview = exp_mgr.get_database_size_preview()
        print("\n" + "=" * 60)
        print("         PORTABLE DATABASE EXPORT PREVIEW")
        print("=" * 60)
        print(f"  Source Database Size:  {format_bytes(preview['actual_db_size'])}")
        print(f"  Valid Documents:       {preview['total_documents']:,}")
        print(f"  Indexed Paragraphs:    {preview['total_paragraphs']:,}")
        print(f"  Extracted Text Size:   {format_bytes(preview['extracted_text_size'])}")
        print(f"  Package Type:          {args.type.upper()}")
        print(f"  Zstandard Compressed:  {'YES (Level ' + str(args.level) + ')' if args.compress else 'NO'}")
        print(f"  Destination Path:      {args.output}")
        print("=" * 60)

        out_path = Path(args.output)
        if args.type == "search-only":
            res = exp_mgr.export_search_only_database(out_path, compress=args.compress, compression_level=args.level)
        elif args.type == "full":
            res = exp_mgr.export_full_database(out_path, compress=args.compress, compression_level=args.level)
        else:
            since = args.since or "2000-01-01"
            res = exp_mgr.export_incremental_package(out_path, since_date=since, compress=args.compress, compression_level=args.level)

        final_sz = format_bytes(res.compressed_size or res.uncompressed_size)
        orig_sz = format_bytes(res.uncompressed_size)

        print("\n" + "=" * 60)
        print("               EXPORT COMPLETED")
        print("=" * 60)
        print(f"  Exported File:         {res.output_path}")
        print(f"  Uncompressed Size:     {orig_sz}")
        print(f"  Final File Size:       {final_sz} ({res.compression_ratio_str})")
        print(f"  Documents:             {res.total_documents:,}")
        print(f"  Paragraphs:            {res.total_paragraphs:,}")
        print(f"  Execution Time:        {res.execution_time_ms:.1f} ms")
        print(f"  SHA-256 Checksum:      {res.sha256_checksum}")
        print("=" * 60 + "\n")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
