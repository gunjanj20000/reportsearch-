"""Automated unit and integration tests for Portable Database Export and Zstandard compression."""

import os
import sqlite3
import tempfile
from pathlib import Path
import pytest

from PySide6.QtWidgets import QApplication

from indexer.database.connection import DatabaseManager
from indexer.export.exporter import ExportManager, ExportType, decompress_file_zstd
from indexer.export.delta_package import IncrementalUpdatePackage
from indexer.models import ExtractedDocument, ExtractedPage, ExtractedParagraph, ExtractionStatus
from indexer.ui.export_dialog import ExportDialog


@pytest.fixture
def populated_db():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "export_test.db"
        db = DatabaseManager(db_path)

        # 1. Valid document
        doc1 = ExtractedDocument(
            filename="Guideline_IVUS.pdf",
            extension=".pdf",
            file_size=80000,
            modified_time=1700000000.0,
            sha256="hash_ivus_1",
            source_path="/docs/Guideline_IVUS.pdf",
            title="IVUS Guidance in Complex Angioplasty",
            page_count=2,
            extraction_status=ExtractionStatus.INDEXED.value,
            pages=[ExtractedPage(page_number=1, text="IVUS guidance ensures minimum stent area expansion.")],
            paragraphs=[ExtractedParagraph(page_number=1, paragraph_number=1, text="IVUS guidance ensures minimum stent area expansion.")]
        )
        db.save_document(doc1)

        # 2. Corrupted document with error status
        doc2 = ExtractedDocument(
            filename="Corrupted_Doc.docx",
            extension=".docx",
            file_size=500,
            modified_time=1700000000.0,
            sha256="hash_bad",
            source_path="/docs/Corrupted_Doc.docx",
            extraction_status=ExtractionStatus.ERROR.value,
            error_message="Bad ZIP header"
        )
        db.save_document(doc2)

        yield db
        db.close()


def test_database_size_preview(populated_db):
    exp_mgr = ExportManager(populated_db)
    preview = exp_mgr.get_database_size_preview()

    assert preview["actual_db_size"] > 0
    assert preview["total_documents"] == 1  # Only successful indexed doc
    assert preview["total_paragraphs"] == 1
    assert preview["extracted_text_size"] > 0


def test_export_search_only_uncompressed(populated_db):
    exp_mgr = ExportManager(populated_db)

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_file = Path(tmp_dir) / "search_compact.db"
        res = exp_mgr.export_search_only_database(out_file, compress=False)

        assert res.export_type == ExportType.SEARCH_ONLY.value
        assert res.output_path.exists()
        assert res.is_compressed is False
        assert len(res.sha256_checksum) == 64
        assert res.total_documents == 1
        assert res.total_paragraphs == 1

        # Verify exported SQLite database integrity directly
        conn = sqlite3.connect(str(out_file))
        conn.row_factory = sqlite3.Row

        # Failed document should NOT be in search-only export
        docs = conn.execute("SELECT * FROM documents").fetchall()
        assert len(docs) == 1
        assert docs[0]["filename"] == "Guideline_IVUS.pdf"

        # Verify FTS5 query works on exported file
        fts = conn.execute(
            "SELECT * FROM search_index WHERE search_index MATCH 'IVUS'"
        ).fetchall()
        assert len(fts) == 1
        conn.close()


def test_export_search_only_zstd_compressed(populated_db):
    exp_mgr = ExportManager(populated_db)

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_file = Path(tmp_dir) / "search_compact.db.zst"
        res = exp_mgr.export_search_only_database(out_file, compress=True, compression_level=5)

        assert res.is_compressed is True
        assert res.compressed_size is not None
        assert res.compressed_size < res.uncompressed_size
        assert res.output_path.exists()
        assert res.output_path.suffix == ".zst"

        # Test decompression and verify decompressed SQLite database
        decomp_file = Path(tmp_dir) / "decompressed.db"
        sz = decompress_file_zstd(res.output_path, decomp_file)
        assert sz == res.uncompressed_size

        conn = sqlite3.connect(str(decomp_file))
        assert conn.execute("SELECT COUNT(*) FROM search_index").fetchone()[0] == 1
        conn.close()


def test_export_full_database(populated_db):
    exp_mgr = ExportManager(populated_db)

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_file = Path(tmp_dir) / "full_backup.db"
        res = exp_mgr.export_full_database(out_file, compress=False)

        assert res.export_type == ExportType.FULL.value
        assert res.output_path.exists()
        assert res.total_documents == 2  # Includes error document in full backup
        assert len(res.sha256_checksum) == 64


def test_export_incremental_package(populated_db):
    exp_mgr = ExportManager(populated_db)

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_file = Path(tmp_dir) / "delta.json"
        res = exp_mgr.export_incremental_package(out_file, since_date="2020-01-01", compress=False)

        assert res.export_type == ExportType.INCREMENTAL.value
        assert res.output_path.exists()
        assert res.total_documents == 1

        # Deserialize JSON package
        content = out_file.read_text(encoding="utf-8")
        pkg = IncrementalUpdatePackage.from_json(content)

        assert pkg.since_date == "2020-01-01"
        assert len(pkg.documents) == 1
        assert pkg.documents[0]["filename"] == "Guideline_IVUS.pdf"
        assert len(pkg.paragraphs) == 1


def test_export_dialog_offscreen_gui(populated_db, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance() or QApplication([])

    with tempfile.TemporaryDirectory() as tmp_dir:
        dialog = ExportDialog(populated_db)
        assert dialog.windowTitle() == "Export Portable Search Database"
        assert dialog.rb_search_only.isChecked()
        assert dialog.chk_compress.isChecked()

        # Set export target
        target = Path(tmp_dir) / "gui_export_test.db.zst"
        dialog.txt_dest.setText(str(target))

        # Run export
        dialog._run_export()

        assert target.exists()
        assert target.stat().st_size > 0
        assert "completed" in dialog.lbl_status.text().lower()
