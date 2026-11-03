"""Dialog for viewing, adding, editing, and deleting cardiology synonyms."""

from __future__ import annotations
import sqlite3
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QLineEdit, QHeaderView, QMessageBox, QCheckBox
)
from PySide6.QtCore import Qt

from ..search.synonyms import SynonymManager


class SynonymsDialog(QDialog):
    """User-facing dialog to view and manage cardiology and medical synonym dictionary."""

    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cardiology Synonym Dictionary")
        self.resize(650, 480)
        self.conn = conn
        self.manager = SynonymManager(self.conn)

        self._init_ui()
        self._load_data()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        desc = QLabel(
            "Cardiology abbreviations and synonyms used for optional query expansion.\n"
            "Enable, disable, or add custom clinical terms below:"
        )
        desc.setStyleSheet("color: #475569;")
        layout.addWidget(desc)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["ID", "Term / Acronym", "Clinical Expansion", "Enabled"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.table)

        # Add new synonym form
        add_layout = QHBoxLayout()
        self.txt_term = QLineEdit()
        self.txt_term.setPlaceholderText("Acronym (e.g. IVL)")
        self.txt_term.setMaximumWidth(120)

        self.txt_expansion = QLineEdit()
        self.txt_expansion.setPlaceholderText("Full Clinical Term (e.g. Intravascular Lithotripsy)")

        self.btn_add = QPushButton("Add Synonym")
        self.btn_add.setStyleSheet("background-color: #2563eb; color: white; font-weight: bold; padding: 6px 12px;")
        self.btn_add.clicked.connect(self._add_synonym)

        add_layout.addWidget(self.txt_term)
        add_layout.addWidget(self.txt_expansion)
        add_layout.addWidget(self.btn_add)
        layout.addLayout(add_layout)

        # Action buttons
        btn_bar = QHBoxLayout()
        self.btn_delete = QPushButton("Delete Selected")
        self.btn_delete.clicked.connect(self._delete_selected)

        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.accept)

        btn_bar.addWidget(self.btn_delete)
        btn_bar.addStretch()
        btn_bar.addWidget(self.btn_close)
        layout.addLayout(btn_bar)

    def _load_data(self) -> None:
        self.table.setRowCount(0)
        syns = self.manager.get_all()

        for row_idx, s in enumerate(syns):
            self.table.insertRow(row_idx)

            id_item = QTableWidgetItem(str(s["synonym_id"]))
            id_item.setFlags(id_item.flags() ^ Qt.ItemIsEditable)
            self.table.setItem(row_idx, 0, id_item)

            term_item = QTableWidgetItem(s["term"])
            self.table.setItem(row_idx, 1, term_item)

            exp_item = QTableWidgetItem(s["expansion"])
            self.table.setItem(row_idx, 2, exp_item)

            status_item = QTableWidgetItem("Yes" if s["enabled"] else "No")
            status_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 3, status_item)

    def _add_synonym(self) -> None:
        term = self.txt_term.text().strip()
        expansion = self.txt_expansion.text().strip()
        if not term or not expansion:
            QMessageBox.warning(self, "Input Error", "Please provide both an acronym and full clinical expansion.")
            return

        try:
            self.manager.add(term, expansion)
            self.txt_term.clear()
            self.txt_expansion.clear()
            self._load_data()
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Duplicate", f"The term '{term}' already exists in the dictionary.")

    def _delete_selected(self) -> None:
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return

        row = selected_rows[0].row()
        syn_id = int(self.table.item(row, 0).text())
        term = self.table.item(row, 1).text()

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to remove the synonym for '{term}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.manager.delete(syn_id)
            self._load_data()
