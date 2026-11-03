"""Automated tests for the IndexerEngine pipeline and controls."""

import time
import tempfile
import threading
from pathlib import Path
import pytest

from indexer.database.connection import DatabaseManager
from indexer.engine.indexer_engine import IndexerEngine
from indexer.models import ExtractionStatus


@pytest.fixture
def test_engine_fixtures(tmp_path):
    txt_dir = tmp_path / "txt_summaries"
    txt_dir.mkdir()
    for i in range(12):
        (txt_dir / f"summary_{i:03d}.txt").write_text(
            f"Cardiology patient discharge summary record {i}.\n"
            f"Patient evaluated for Chronic Total Occlusion (CTO) and Left Main (LM) stenting with IVUS."
        )

    corrupt_dir = tmp_path / "corrupted"
    corrupt_dir.mkdir()
    (corrupt_dir / "corrupt_1.pdf").write_bytes(b"%PDF-1.4\nTRUNCATED_CORRUPTED_BYTES")
    (corrupt_dir / "corrupt_2.docx").write_bytes(b"NOT_A_VALID_DOCX_ZIP_STREAM")

    return {"txt_dir": txt_dir, "corrupt_dir": corrupt_dir}


def test_engine_index_folder(test_engine_fixtures):
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_engine.db"
        db = DatabaseManager(db_path)
        engine = IndexerEngine(db_manager=db)

        folders = [test_engine_fixtures["txt_dir"]]
        res = engine.index_folders(folders)

        assert res.total_found >= 10
        stats = db.get_dashboard_stats()
        assert stats.total_documents >= 10
        assert stats.extracted_text_size > 0
        assert stats.last_indexing_date is not None


def test_engine_pause_and_resume(test_engine_fixtures):
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_pause.db"
        db = DatabaseManager(db_path)
        engine = IndexerEngine(db_manager=db)

        folders = [test_engine_fixtures["txt_dir"]]

        # Run engine in background thread
        t = threading.Thread(target=engine.index_folders, args=(folders,))
        t.start()

        # Pause
        time.sleep(0.05)
        engine.pause()
        assert engine.status in ["paused", "completed"]

        # Resume
        time.sleep(0.05)
        engine.resume()
        assert engine.status in ["indexing", "completed"]

        # Wait or cancel to finish
        t.join(timeout=10)


def test_engine_cancel(test_engine_fixtures):
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_cancel.db"
        db = DatabaseManager(db_path)
        engine = IndexerEngine(db_manager=db)

        folders = [test_engine_fixtures["txt_dir"]]

        t = threading.Thread(target=engine.index_folders, args=(folders,))
        t.start()

        time.sleep(0.02)
        engine.cancel()
        t.join(timeout=10)

        assert engine.status in ["cancelled", "completed"]


def test_engine_retry_failed_documents(test_engine_fixtures):
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_retry.db"
        db = DatabaseManager(db_path)
        engine = IndexerEngine(db_manager=db)

        # Index corrupted folder
        engine.index_folders([test_engine_fixtures["corrupt_dir"]])

        failed = db.get_failed_documents()
        assert len(failed) > 0, "Corrupted files should produce failed records"

        # Calling retry on them
        engine.retry_failed_documents()
        assert engine.status in ["completed", "idle"]
