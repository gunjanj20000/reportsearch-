"""Core Indexer Engine orchestrating scanning, extraction, persistence, and state controls."""

from __future__ import annotations
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional

from ..config import logger, DEFAULT_DB_PATH
from ..models import ExtractedDocument, DashboardStats, ExtractionStatus
from ..database.connection import DatabaseManager
from ..extractors.factory import ExtractorFactory, default_factory
from ..scanner.scanner import FileScanner, ScanResult, ScannedFile


class IndexerEngine:
    """Orchestrates indexing lifecycle with pause, resume, cancel, and incremental sync."""

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        extractor_factory: Optional[ExtractorFactory] = None
    ):
        self.db = db_manager or DatabaseManager(DEFAULT_DB_PATH)
        self.factory = extractor_factory or default_factory
        self.scanner = FileScanner()

        # Thread synchronization and control flags
        self._pause_event = threading.Event()
        self._pause_event.set()  # Set means "running" (not paused)
        self._cancel_requested = threading.Event()
        self._is_running = threading.Event()

        # Callbacks for UI or CLI decoupling
        self.on_progress: Optional[Callable[[int, int, str, str], None]] = None
        self.on_file_indexed: Optional[Callable[[ExtractedDocument], None]] = None
        self.on_status_changed: Optional[Callable[[str], None]] = None
        self.on_stats_updated: Optional[Callable[[DashboardStats], None]] = None
        self.on_error: Optional[Callable[[str, str], None]] = None

        self._current_status = "idle"

    @property
    def status(self) -> str:
        return self._current_status

    def _set_status(self, status: str) -> None:
        self._current_status = status
        logger.info(f"Engine status changed to: {status}")
        if self.on_status_changed:
            self.on_status_changed(status)

    def pause(self) -> None:
        """Pause indexing."""
        if self._is_running.is_set() and self._pause_event.is_set():
            self._pause_event.clear()
            self._set_status("paused")

    def resume(self) -> None:
        """Resume indexing."""
        if self._is_running.is_set() and not self._pause_event.is_set():
            self._pause_event.set()
            self._set_status("indexing")

    def cancel(self) -> None:
        """Cancel current indexing run."""
        if self._is_running.is_set():
            self._cancel_requested.set()
            self._pause_event.set()  # Unblock if currently paused
            self._set_status("cancelling")

    def index_folders(self, folders: List[Path | str]) -> ScanResult:
        """
        Main entry point for scanning and indexing given folder paths.
        Executes incrementally and notifies progress callbacks.
        """
        if self._is_running.is_set():
            raise RuntimeError("Indexing is already running.")

        self._is_running.set()
        self._cancel_requested.clear()
        self._pause_event.set()

        try:
            self._set_status("scanning")
            if self.on_progress:
                self.on_progress(0, 0, "", "Scanning folders for documents...")

            existing_paths = self.db.get_all_indexed_paths()
            scan_result = self.scanner.scan(folders, existing_paths)

            # Handle deleted files
            if scan_result.deleted:
                logger.info(f"Removing {len(scan_result.deleted)} deleted files from database...")
                for deleted_path in scan_result.deleted:
                    self.db.delete_document_by_path(deleted_path)

            total_to_index = len(scan_result.to_index)
            if total_to_index == 0:
                logger.info("No new or modified files found to index.")
                self._set_status("completed")
                if self.on_progress:
                    self.on_progress(0, 0, "", "All documents are up to date.")
                if self.on_stats_updated:
                    self.on_stats_updated(self.db.get_dashboard_stats())
                return scan_result

            self._set_status("indexing")
            logger.info(f"Starting extraction for {total_to_index} documents...")

            for idx, item in enumerate(scan_result.to_index, start=1):
                # Check for cancellation
                if self._cancel_requested.is_set():
                    logger.info("Indexing cancelled by user request.")
                    self._set_status("cancelled")
                    if self.on_progress:
                        self.on_progress(idx - 1, total_to_index, str(item.path), "Indexing cancelled.")
                    break

                # Check for pause
                while not self._pause_event.is_set():
                    if self._cancel_requested.is_set():
                        break
                    time.sleep(0.2)

                if self._cancel_requested.is_set():
                    self._set_status("cancelled")
                    break

                current_filename = item.path.name
                if self.on_progress:
                    self.on_progress(
                        idx,
                        total_to_index,
                        current_filename,
                        f"Indexing ({idx}/{total_to_index}): {current_filename}"
                    )

                # Extract content
                doc = self.factory.extract(item.path)

                # Persist to database
                self.db.save_document(doc)

                if doc.extraction_status == ExtractionStatus.ERROR.value:
                    if self.on_error:
                        self.on_error(str(item.path), doc.error_message or "Unknown extraction error")
                elif self.on_file_indexed:
                    self.on_file_indexed(doc)

                # Update stats periodically
                if idx % 5 == 0 or idx == total_to_index:
                    if self.on_stats_updated:
                        stats = self.db.get_dashboard_stats()
                        stats.indexing_progress = (idx / total_to_index) * 100.0
                        self.on_stats_updated(stats)

            if not self._cancel_requested.is_set():
                self._set_status("completed")
                if self.on_progress:
                    self.on_progress(total_to_index, total_to_index, "", "Indexing complete.")

            if self.on_stats_updated:
                self.on_stats_updated(self.db.get_dashboard_stats())

            return scan_result

        finally:
            self._is_running.clear()
            if self.status not in ["completed", "cancelled"]:
                self._set_status("idle")

    def retry_failed_documents(self) -> int:
        """Find all documents with extraction errors and re-attempt extraction."""
        failed_docs = self.db.get_failed_documents()
        if not failed_docs:
            logger.info("No failed documents found to retry.")
            return 0

        logger.info(f"Retrying extraction for {len(failed_docs)} failed documents...")
        self._is_running.set()
        self._cancel_requested.clear()
        self._pause_event.set()
        self._set_status("indexing")

        succeeded = 0
        total = len(failed_docs)

        try:
            for idx, r in enumerate(failed_docs, start=1):
                if self._cancel_requested.is_set():
                    break

                p = Path(r["source_path"])
                if self.on_progress:
                    self.on_progress(idx, total, p.name, f"Retrying ({idx}/{total}): {p.name}")

                if not p.exists():
                    logger.warning(f"File no longer exists: {p}")
                    self.db.delete_document_by_path(str(p))
                    continue

                doc = self.factory.extract(p)
                self.db.save_document(doc)

                if doc.extraction_status != ExtractionStatus.ERROR.value:
                    succeeded += 1
                    if self.on_file_indexed:
                        self.on_file_indexed(doc)
                elif self.on_error:
                    self.on_error(str(p), doc.error_message or "Retry failed")

            self._set_status("completed")
            if self.on_stats_updated:
                self.on_stats_updated(self.db.get_dashboard_stats())
            return succeeded

        finally:
            self._is_running.clear()
            if self.status not in ["completed", "cancelled"]:
                self._set_status("idle")
