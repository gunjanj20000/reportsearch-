"""Main Window for the Medical Literature Indexer desktop application."""

from __future__ import annotations
import sys
from pathlib import Path
from typing import List

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QListWidget, QProgressBar, QTextEdit, QFileDialog,
    QMessageBox, QGroupBox, QSplitter, QStatusBar, QFrame, QTabWidget
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon

from .dashboard_widget import DashboardWidget
from .search_tab import SearchTab
from .export_dialog import ExportDialog
from .worker import IndexerWorker
from ..engine.indexer_engine import IndexerEngine
from ..models import DashboardStats, ExtractedDocument
from ..config import (
    logger, find_libreoffice_binary, find_tesseract_binary,
    DEFAULT_DB_PATH
)


class MainWindow(QMainWindow):
    """Main desktop interface for document indexing, folder management, and dashboard."""

    def __init__(self, engine: IndexerEngine | None = None):
        super().__init__()
        self.setWindowTitle("Medical Literature Search — Windows Indexer")
        self.resize(1150, 850)
        self.setMinimumSize(950, 700)

        self.engine = engine or IndexerEngine()
        self.worker: IndexerWorker | None = None
        self.selected_folders: List[Path] = []

        self._init_ui()
        self._load_folders()
        self._check_dependencies()
        self._refresh_stats()

    def _init_ui(self) -> None:
        self.tabs = QTabWidget(self)
        self.setCentralWidget(self.tabs)

        # Tab 1: Indexing & Dashboard
        indexer_tab = QWidget()
        indexer_layout = QVBoxLayout(indexer_tab)
        indexer_layout.setContentsMargins(16, 16, 16, 16)
        indexer_layout.setSpacing(14)

        # 1. Header
        header_layout = QHBoxLayout()
        header_title = QLabel("Medical Literature Search Indexer")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        header_title.setFont(title_font)
        header_layout.addWidget(header_title)
        header_layout.addStretch()

        self.btn_refresh = QPushButton("Refresh Stats")
        self.btn_refresh.clicked.connect(self._refresh_stats)
        header_layout.addWidget(self.btn_refresh)
        indexer_layout.addLayout(header_layout)

        # 2. Dashboard
        self.dashboard = DashboardWidget(self)
        indexer_layout.addWidget(self.dashboard)

        # 3. Middle Section: Folders (Left) & Controls/Progress (Right)
        middle_splitter = QSplitter(Qt.Horizontal)

        # Left: Folder Selection
        folder_group = QGroupBox("Source Folders (Internal, USB, Network, Google Drive Sync)")
        folder_layout = QVBoxLayout(folder_group)

        self.folder_list = QListWidget()
        folder_layout.addWidget(self.folder_list)

        folder_btn_layout = QHBoxLayout()
        self.btn_add_folder = QPushButton("Add Folder...")
        self.btn_add_folder.clicked.connect(self._add_folder)
        self.btn_remove_folder = QPushButton("Remove Selected")
        self.btn_remove_folder.clicked.connect(self._remove_folder)
        self.btn_clear_folders = QPushButton("Clear All")
        self.btn_clear_folders.clicked.connect(self._clear_folders)

        folder_btn_layout.addWidget(self.btn_add_folder)
        folder_btn_layout.addWidget(self.btn_remove_folder)
        folder_btn_layout.addWidget(self.btn_clear_folders)
        folder_layout.addLayout(folder_btn_layout)
        middle_splitter.addWidget(folder_group)

        # Right: Actions & Progress
        control_group = QGroupBox("Indexing Actions & Progress")
        control_layout = QVBoxLayout(control_group)

        # Action Buttons
        btn_grid_layout = QHBoxLayout()
        self.btn_start = QPushButton("Start Indexing")
        self.btn_start.setStyleSheet("background-color: #059669; color: white; font-weight: bold; padding: 8px;")
        self.btn_start.clicked.connect(self._start_indexing)

        self.btn_pause = QPushButton("Pause")
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self._pause_indexing)

        self.btn_resume = QPushButton("Resume")
        self.btn_resume.setEnabled(False)
        self.btn_resume.clicked.connect(self._resume_indexing)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setStyleSheet("background-color: #dc2626; color: white; font-weight: bold;")
        self.btn_cancel.clicked.connect(self._cancel_indexing)

        btn_grid_layout.addWidget(self.btn_start)
        btn_grid_layout.addWidget(self.btn_pause)
        btn_grid_layout.addWidget(self.btn_resume)
        btn_grid_layout.addWidget(self.btn_cancel)
        control_layout.addLayout(btn_grid_layout)

        # Secondary Actions
        sec_btn_layout = QHBoxLayout()
        self.btn_export_db = QPushButton("Export Portable DB...")
        self.btn_export_db.setStyleSheet("background-color: #0284c7; color: white; font-weight: bold;")
        self.btn_export_db.clicked.connect(self._open_export_dialog)

        self.btn_retry_failed = QPushButton("Retry Failed Documents")
        self.btn_retry_failed.clicked.connect(self._retry_failed)

        self.btn_clear_db = QPushButton("Reset Database")
        self.btn_clear_db.clicked.connect(self._clear_database)

        sec_btn_layout.addWidget(self.btn_export_db)
        sec_btn_layout.addWidget(self.btn_retry_failed)
        sec_btn_layout.addWidget(self.btn_clear_db)
        control_layout.addLayout(sec_btn_layout)

        # Progress display
        control_layout.addSpacing(10)
        self.lbl_status = QLabel("Status: Idle")
        self.lbl_status.setStyleSheet("font-weight: 600; color: #334155;")
        control_layout.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        control_layout.addWidget(self.progress_bar)

        self.lbl_current_file = QLabel("")
        self.lbl_current_file.setStyleSheet("color: #64748b; font-size: 11px;")
        self.lbl_current_file.setWordWrap(True)
        control_layout.addWidget(self.lbl_current_file)
        control_layout.addStretch()

        middle_splitter.addWidget(control_group)
        indexer_layout.addWidget(middle_splitter, stretch=2)

        # 4. Activity & Live Log
        log_group = QGroupBox("Activity & Extraction Logs")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e293b;
                color: #f8fafc;
                font-family: monospace;
                font-size: 11px;
                border-radius: 4px;
            }
        """)
        log_layout.addWidget(self.log_text)

        log_btn_layout = QHBoxLayout()
        log_btn_layout.addStretch()
        self.btn_clear_log = QPushButton("Clear Logs")
        self.btn_clear_log.clicked.connect(self.log_text.clear)
        log_btn_layout.addWidget(self.btn_clear_log)
        log_layout.addLayout(log_btn_layout)

        indexer_layout.addWidget(log_group, stretch=1)

        # Tab 2: Full-text Search
        self.search_tab = SearchTab(self.engine.db, self)

        # Add tabs
        self.tabs.addTab(indexer_tab, "Indexer & Dashboard")
        self.tabs.addTab(self.search_tab, "Search Library (FTS5)")

        # 5. Status Bar with Dependency Checks
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

    def _open_export_dialog(self) -> None:
        dialog = ExportDialog(self.engine.db, self)
        dialog.exec()

    def _check_dependencies(self) -> None:
        """Check availability of external conversion and OCR dependencies."""
        lo_path = find_libreoffice_binary()
        tess_path = find_tesseract_binary()

        lo_status = "LibreOffice: OK" if lo_path else "LibreOffice: MISSING (legacy .doc disabled)"
        tess_status = "Tesseract OCR: OK" if tess_path else "Tesseract OCR: MISSING (scanned PDF OCR disabled)"

        msg = f"Dependencies:  {lo_status}  |  {tess_status}  |  DB: {DEFAULT_DB_PATH.name}"
        self.status_bar.showMessage(msg)

        if not lo_path:
            self._log("[WARNING] LibreOffice not found. Legacy .doc conversion will report errors.")
        if not tess_path:
            self._log("[WARNING] Tesseract OCR not found. Scanned PDF text extraction will be limited.")

    def _log(self, text: str) -> None:
        self.log_text.append(text)
        # Scroll to bottom
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _refresh_stats(self) -> None:
        stats = self.engine.db.get_dashboard_stats()
        self.dashboard.update_stats(stats)

    def _load_folders(self) -> None:
        """Load configured indexed folders from SQLite into UI list."""
        folders = self.engine.db.get_indexed_folders()
        self.selected_folders.clear()
        self.folder_list.clear()
        for f in folders:
            p = Path(f["folder_path"])
            self.selected_folders.append(p)
            self.folder_list.addItem(f["folder_path"])

    def _add_folder(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(self, "Select Document Folder")
        if dir_path:
            p = Path(dir_path).resolve()
            if p not in self.selected_folders:
                self.selected_folders.append(p)
                self.folder_list.addItem(str(p))
                self.engine.db.add_indexed_folder(str(p))
                self._log(f"Added folder: {p}")

    def _remove_folder(self) -> None:
        current_row = self.folder_list.currentRow()
        if current_row >= 0:
            removed = self.selected_folders.pop(current_row)
            self.folder_list.takeItem(current_row)
            folders = self.engine.db.get_indexed_folders()
            for f in folders:
                if f["folder_path"] == str(removed):
                    self.engine.db.remove_indexed_folder(f["folder_id"])
                    break
            self._log(f"Removed folder: {removed}")

    def _clear_folders(self) -> None:
        folders = self.engine.db.get_indexed_folders()
        for f in folders:
            self.engine.db.remove_indexed_folder(f["folder_id"])
        self.selected_folders.clear()
        self.folder_list.clear()
        self._log("Cleared all source folders.")

    def _set_ui_state_indexing(self) -> None:
        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_resume.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_retry_failed.setEnabled(False)
        self.btn_clear_db.setEnabled(False)
        self.btn_add_folder.setEnabled(False)
        self.btn_remove_folder.setEnabled(False)
        self.btn_clear_folders.setEnabled(False)

    def _set_ui_state_paused(self) -> None:
        self.btn_pause.setEnabled(False)
        self.btn_resume.setEnabled(True)
        self.btn_cancel.setEnabled(True)

    def _set_ui_state_idle(self) -> None:
        self.btn_start.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_resume.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.btn_retry_failed.setEnabled(True)
        self.btn_clear_db.setEnabled(True)
        self.btn_add_folder.setEnabled(True)
        self.btn_remove_folder.setEnabled(True)
        self.btn_clear_folders.setEnabled(True)

    def _start_indexing(self) -> None:
        if not self.selected_folders:
            QMessageBox.warning(self, "No Folders Selected", "Please add at least one folder before indexing.")
            return

        self._set_ui_state_indexing()
        self.lbl_status.setText("Status: Scanning and indexing...")
        self.progress_bar.setValue(0)
        self._log("=== Indexing session started ===")

        self.worker = IndexerWorker(self.engine, self.selected_folders, retry_mode=False)
        self._connect_worker()
        self.worker.start()

    def _retry_failed(self) -> None:
        failed = self.engine.db.get_failed_documents()
        if not failed:
            QMessageBox.information(self, "No Failures", "There are no failed documents to retry.")
            return

        self._set_ui_state_indexing()
        self.lbl_status.setText(f"Status: Retrying {len(failed)} failed documents...")
        self.progress_bar.setValue(0)
        self._log(f"=== Retrying {len(failed)} failed documents ===")

        self.worker = IndexerWorker(self.engine, self.selected_folders, retry_mode=True)
        self._connect_worker()
        self.worker.start()

    def _connect_worker(self) -> None:
        if not self.worker:
            return
        self.worker.progress_signal.connect(self._on_progress)
        self.worker.stats_signal.connect(self.dashboard.update_stats)
        self.worker.file_indexed_signal.connect(self._on_file_indexed)
        self.worker.status_signal.connect(self._on_status_changed)
        self.worker.error_signal.connect(self._on_error)
        self.worker.finished_signal.connect(self._on_finished)

    def _pause_indexing(self) -> None:
        self.engine.pause()
        self._set_ui_state_paused()
        self.lbl_status.setText("Status: Paused")
        self._log("[INFO] Indexing paused by user.")

    def _resume_indexing(self) -> None:
        self.engine.resume()
        self._set_ui_state_indexing()
        self.lbl_status.setText("Status: Resumed indexing...")
        self._log("[INFO] Indexing resumed.")

    def _cancel_indexing(self) -> None:
        self.engine.cancel()
        self.lbl_status.setText("Status: Cancelling...")
        self._log("[INFO] Indexing cancellation requested...")

    def _clear_database(self) -> None:
        reply = QMessageBox.question(
            self,
            "Reset Database",
            "Are you sure you want to completely clear the search database?\nAll indexed document records will be wiped.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.engine.db.clear_database()
            self._load_folders()
            self._refresh_stats()
            self._log("[INFO] Database wiped successfully.")
            QMessageBox.information(self, "Database Reset", "The database has been cleared.")

    def _on_progress(self, current: int, total: int, filename: str, msg: str) -> None:
        self.lbl_status.setText(f"Status: {msg}")
        if filename:
            self.lbl_current_file.setText(f"Processing: {filename}")
        if total > 0:
            pct = int((current / total) * 100)
            self.progress_bar.setValue(pct)

    def _on_file_indexed(self, doc: ExtractedDocument) -> None:
        status_tag = f"[{doc.extraction_status.upper()}]"
        self._log(f"{status_tag} {doc.filename} — {doc.page_count} pages, {len(doc.paragraphs)} paragraphs")

    def _on_error(self, path: str, err: str) -> None:
        self._log(f"[ERROR] {Path(path).name}: {err}")

    def _on_status_changed(self, status: str) -> None:
        self.lbl_status.setText(f"Status: {status.capitalize()}")

    def _on_finished(self, result: object) -> None:
        self._set_ui_state_idle()
        self._refresh_stats()
        self._log("=== Indexing session finished ===")
        self.lbl_current_file.setText("")
        self.worker = None
