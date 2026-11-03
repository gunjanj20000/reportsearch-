"""Automated tests for PySide6 MainWindow and Dashboard offscreen."""

import os
import tempfile
from pathlib import Path
import pytest

from PySide6.QtWidgets import QApplication

from indexer.database.connection import DatabaseManager
from indexer.engine.indexer_engine import IndexerEngine
from indexer.ui.main_window import MainWindow
from indexer.models import DashboardStats


@pytest.fixture(scope="session")
def qapp():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_main_window_initialization(qapp):
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_gui.db"
        db = DatabaseManager(db_path)
        engine = IndexerEngine(db_manager=db)

        window = MainWindow(engine=engine)
        assert window.windowTitle() == "Medical Literature Search — Windows Indexer"
        assert window.dashboard is not None
        assert window.folder_list.count() == 0

        # Test folder manipulation
        test_dir = Path(tmp_dir) / "sample_folder"
        test_dir.mkdir()
        window.selected_folders.append(test_dir)
        window.folder_list.addItem(str(test_dir))
        assert window.folder_list.count() == 1

        window.folder_list.setCurrentRow(0)
        window._remove_folder()
        assert window.folder_list.count() == 0


def test_dashboard_widget_updates(qapp):
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_dash.db"
        db = DatabaseManager(db_path)
        engine = IndexerEngine(db_manager=db)
        window = MainWindow(engine=engine)

        custom_stats = DashboardStats(
            total_documents=125,
            total_original_file_size=52428800,  # 50 MB
            extracted_text_size=1048576,        # 1 MB
            database_size=2097152,              # 2 MB
            number_of_pdf_pages=450,
            number_of_word_documents=60,
            number_of_scanned_pdfs=15,
            indexing_progress=100.0,
            last_indexing_date="2026-11-03 10:00:00"
        )
        window.dashboard.update_stats(custom_stats)

        assert window.dashboard.card_total_docs.value_label.text() == "125"
        assert "50.00 MB" in window.dashboard.card_orig_size.value_label.text()
        assert "1.00 MB" in window.dashboard.card_extracted_size.value_label.text()
        assert "2.00 MB" in window.dashboard.card_db_size.value_label.text()
        assert window.dashboard.card_pdf_pages.value_label.text() == "450"
        assert window.dashboard.card_word_docs.value_label.text() == "60"
        assert window.dashboard.card_scanned_pdfs.value_label.text() == "15"
        assert window.dashboard.card_last_indexed.value_label.text() == "2026-11-03 10:00:00"
