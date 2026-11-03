"""Automated tests for the IndexerEngine pipeline and controls."""

import time
import tempfile
import threading
from pathlib import Path

from indexer.database.connection import DatabaseManager
from indexer.engine.indexer_engine import IndexerEngine
from indexer.models import ExtractionStatus

CORPUS_DIR = Path("/home/ubuntu/searchengine/sample_corpus")


def test_engine_index_folder():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_engine.db"
        db = DatabaseManager(db_path)
        engine = IndexerEngine(db_manager=db)

        # Index small batch from sample corpus (e.g. txt_summaries)
        folders = [CORPUS_DIR / "txt_summaries"]
        res = engine.index_folders(folders)

        assert res.total_found >= 10
        stats = db.get_dashboard_stats()
        assert stats.total_documents >= 10
        assert stats.extracted_text_size > 0
        assert stats.last_indexing_date is not None


def test_engine_pause_and_resume():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_pause.db"
        db = DatabaseManager(db_path)
        engine = IndexerEngine(db_manager=db)

        folders = [CORPUS_DIR / "docx_trials"]

        # Run engine in background thread
        t = threading.Thread(target=engine.index_folders, args=(folders,))
        t.start()

        # Pause
        time.sleep(0.3)
        engine.pause()
        assert engine.status == "paused"

        # Resume
        time.sleep(0.2)
        engine.resume()
        assert engine.status in ["indexing", "completed"]

        # Cancel to finish quickly
        engine.cancel()
        t.join(timeout=10)


def test_engine_cancel():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_cancel.db"
        db = DatabaseManager(db_path)
        engine = IndexerEngine(db_manager=db)

        folders = [CORPUS_DIR / "pdf_guidelines"]

        t = threading.Thread(target=engine.index_folders, args=(folders,))
        t.start()

        time.sleep(0.2)
        engine.cancel()
        t.join(timeout=10)

        assert engine.status == "cancelled"


def test_engine_retry_failed_documents():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_retry.db"
        db = DatabaseManager(db_path)
        engine = IndexerEngine(db_manager=db)

        # Index corrupted folder
        engine.index_folders([CORPUS_DIR / "corrupted"])

        failed = db.get_failed_documents()
        assert len(failed) > 0, "Corrupted files should produce failed records"

        # Calling retry on them
        engine.retry_failed_documents()
        # Verify that engine handled retry loop safely
        assert engine.status in ["completed", "idle"]
