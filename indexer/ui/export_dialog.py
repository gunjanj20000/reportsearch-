"""PySide6 Dialog for exporting portable search databases and incremental packages."""

from __future__ import annotations
import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QRadioButton, QButtonGroup,
    QCheckBox, QLabel, QPushButton, QFileDialog, QProgressBar,
    QMessageBox, QGroupBox, QLineEdit, QDateTimeEdit, QSpinBox
)
from PySide6.QtCore import Qt, QDateTime

from ..export.exporter import ExportManager, ExportType
from ..database.connection import DatabaseManager
from ..ui.dashboard_widget import format_bytes


class ExportDialog(QDialog):
    """User-facing dialog to export portable databases with Zstandard compression."""

    def __init__(self, db_manager: DatabaseManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Portable Search Database")
        self.resize(650, 600)
        self.db = db_manager
        self.export_manager = ExportManager(self.db)

        self._init_ui()
        self._load_preview()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        # 1. Size Preview Box
        preview_group = QGroupBox("Current Database Status & Size Preview")
        preview_layout = QVBoxLayout(preview_group)

        self.lbl_preview_docs = QLabel("Indexed Documents: Loading...")
        self.lbl_preview_size = QLabel("Actual Database Size: Loading...")
        self.lbl_preview_paras = QLabel("Total Paragraphs: Loading...")

        preview_layout.addWidget(self.lbl_preview_docs)
        preview_layout.addWidget(self.lbl_preview_paras)
        preview_layout.addWidget(self.lbl_preview_size)
        layout.addWidget(preview_group)

        # 2. Export Type Selection
        type_group = QGroupBox("Export Package Type")
        type_layout = QVBoxLayout(type_group)

        self.btn_group_type = QButtonGroup(self)

        self.rb_search_only = QRadioButton("Search-Only Compact Database (Recommended for Mobile PWA)")
        self.rb_search_only.setChecked(True)
        self.rb_search_only.setToolTip(
            "Excludes errors, merges FTS5 b-tree segments into a single compact tree, "
            "and VACUUMs unallocated pages for minimum phone storage footprint."
        )

        self.rb_full = QRadioButton("Full Database (Complete SQLite Clone)")
        self.rb_full.setToolTip("Complete snapshot of all tables, documents, logs, and metadata.")

        self.rb_incremental = QRadioButton("Incremental Update Package (Delta for Mobile Sync)")
        self.rb_incremental.setToolTip("Exports only documents and paragraphs modified since a baseline date.")

        self.btn_group_type.addButton(self.rb_search_only)
        self.btn_group_type.addButton(self.rb_full)
        self.btn_group_type.addButton(self.rb_incremental)

        type_layout.addWidget(self.rb_search_only)
        type_layout.addWidget(self.rb_full)
        type_layout.addWidget(self.rb_incremental)

        # Incremental date selector
        self.inc_box = QHBoxLayout()
        self.lbl_since = QLabel("Changes Since:")
        self.date_since = QDateTimeEdit(QDateTime.currentDateTime().addDays(-7))
        self.date_since.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.date_since.setEnabled(False)
        self.inc_box.addWidget(self.lbl_since)
        self.inc_box.addWidget(self.date_since)
        self.inc_box.addStretch()
        type_layout.addLayout(self.inc_box)

        self.rb_incremental.toggled.connect(self._on_type_changed)
        layout.addWidget(type_group)

        # 3. Compression Options
        comp_group = QGroupBox("Zstandard (zstd) Compression")
        comp_layout = QVBoxLayout(comp_group)

        comp_row = QHBoxLayout()
        self.chk_compress = QCheckBox("Enable Zstandard Compression (.zst)")
        self.chk_compress.setChecked(True)

        comp_row.addWidget(self.chk_compress)
        comp_row.addSpacing(16)
        comp_row.addWidget(QLabel("Level (1-19):"))

        self.spin_level = QSpinBox()
        self.spin_level.setRange(1, 19)
        self.spin_level.setValue(10)
        comp_row.addWidget(self.spin_level)
        comp_row.addStretch()

        comp_layout.addLayout(comp_row)
        layout.addWidget(comp_group)

        # 4. Destination File
        dest_group = QGroupBox("Output Destination")
        dest_layout = QHBoxLayout(dest_group)

        default_out = str(Path.home() / "medical_search_portable.db.zst")
        self.txt_dest = QLineEdit(default_out)
        self.btn_browse = QPushButton("Browse...")
        self.btn_browse.clicked.connect(self._browse_destination)

        dest_layout.addWidget(self.txt_dest)
        dest_layout.addWidget(self.btn_browse)
        layout.addWidget(dest_group)

        # 5. Progress and Status
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("Ready to export.")
        self.lbl_status.setStyleSheet("color: #475569;")
        layout.addWidget(self.lbl_status)

        # 6. Action buttons
        btn_bar = QHBoxLayout()
        self.btn_export = QPushButton("Export Database")
        self.btn_export.setStyleSheet("""
            background-color: #059669; color: white; font-weight: bold;
            font-size: 13px; padding: 8px 16px; border-radius: 6px;
        """)
        self.btn_export.clicked.connect(self._run_export)

        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.reject)

        btn_bar.addStretch()
        btn_bar.addWidget(self.btn_export)
        btn_bar.addWidget(self.btn_close)
        layout.addLayout(btn_bar)

    def _load_preview(self) -> None:
        preview = self.export_manager.get_database_size_preview()
        self.lbl_preview_docs.setText(f"Indexed Documents: <b>{preview['total_documents']:,}</b>")
        self.lbl_preview_paras.setText(f"Total Paragraphs: <b>{preview['total_paragraphs']:,}</b>")
        self.lbl_preview_size.setText(
            f"Current Database File Size: <b>{format_bytes(preview['actual_db_size'])}</b> "
            f"(Extracted text: {format_bytes(preview['extracted_text_size'])})"
        )

    def _on_type_changed(self, is_incremental: bool) -> None:
        self.date_since.setEnabled(is_incremental)
        # Update suggested filename
        if is_incremental:
            ext = ".json.zst" if self.chk_compress.isChecked() else ".json"
            suggested = str(Path.home() / f"medical_delta_{datetime.date.today()}{ext}")
        else:
            ext = ".db.zst" if self.chk_compress.isChecked() else ".db"
            suggested = str(Path.home() / f"medical_search_portable{ext}")
        self.txt_dest.setText(suggested)

    def _browse_destination(self) -> None:
        is_inc = self.rb_incremental.isChecked()
        filter_str = "Delta Package (*.json *.zst)" if is_inc else "SQLite Database (*.db *.zst);;All Files (*.*)"
        path, _ = QFileDialog.getSaveFileName(self, "Select Export Location", self.txt_dest.text(), filter_str)
        if path:
            self.txt_dest.setText(path)

    def _run_export(self) -> None:
        dest_str = self.txt_dest.text().strip()
        if not dest_str:
            QMessageBox.warning(self, "Missing Destination", "Please specify a destination file path.")
            return

        dest_path = Path(dest_str)
        compress = self.chk_compress.isChecked()
        level = self.spin_level.value()

        self.btn_export.setEnabled(False)
        self.lbl_status.setText("Exporting database... please wait.")
        self.progress_bar.setValue(20)

        try:
            if self.rb_search_only.isChecked():
                res = self.export_manager.export_search_only_database(
                    dest_path=dest_path, compress=compress, compression_level=level
                )
            elif self.rb_full.isChecked():
                res = self.export_manager.export_full_database(
                    dest_path=dest_path, compress=compress, compression_level=level
                )
            else:
                since_iso = self.date_since.dateTime().toPython().isoformat()
                res = self.export_manager.export_incremental_package(
                    dest_path=dest_path, since_date=since_iso, compress=compress, compression_level=level
                )

            self.progress_bar.setValue(100)
            self.lbl_status.setText(f"Export completed in {res.execution_time_ms:.1f} ms.")

            # Summary message
            final_size_str = format_bytes(res.compressed_size or res.uncompressed_size)
            orig_size_str = format_bytes(res.uncompressed_size)

            msg = (
                f"Portable export created successfully!\n\n"
                f"• Type: {res.export_type.upper()}\n"
                f"• Output Path: {res.output_path}\n"
                f"• Uncompressed Size: {orig_size_str}\n"
                f"• Final Export Size: {final_size_str} ({res.compression_ratio_str})\n"
                f"• Documents: {res.total_documents:,} | Paragraphs: {res.total_paragraphs:,}\n"
                f"• SHA-256 Checksum:\n  {res.sha256_checksum}\n\n"
                f"This file is ready for offline import into the Mobile Search PWA."
            )
            QMessageBox.information(self, "Export Successful", msg)

        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"An error occurred during export:\n{e}")
            self.lbl_status.setText("Export failed.")
        finally:
            self.btn_export.setEnabled(True)
