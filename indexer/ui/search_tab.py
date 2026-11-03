"""Search Tab widget for the desktop GUI with real-time FTS5 querying, highlighting, and filters."""

from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QLabel, QCheckBox, QScrollArea, QFrame, QCompleter,
    QMessageBox, QButtonGroup, QRadioButton
)
from PySide6.QtCore import Qt, QStringListModel
from PySide6.QtGui import QFont

from .synonyms_dialog import SynonymsDialog
from ..search.search_service import SearchService, SearchResponse, SearchResultItem
from ..database.connection import DatabaseManager


def open_file_externally(file_path: str) -> None:
    """Open a file with the system default application across OSes."""
    p = Path(file_path)
    if not p.exists():
        return

    try:
        if sys.platform == "win32":
            os.startfile(str(p))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(p)], check=False)
        else:
            subprocess.run(["xdg-open", str(p)], check=False)
    except Exception:
        pass


class ResultCard(QFrame):
    """Card widget rendering a single matching search result."""

    def __init__(self, item: SearchResultItem, parent=None):
        super().__init__(parent)
        self.item = item
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("""
            ResultCard {
                background-color: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                padding: 10px;
                margin-bottom: 8px;
            }
            ResultCard:hover {
                border-color: #94a3b8;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Header row: Title + Badges + Open button
        header_layout = QHBoxLayout()

        # Format badge
        ext_upper = item.extension.upper().replace(".", "")
        badge_color = {
            "PDF": "#dc2626",
            "DOCX": "#2563eb",
            "DOC": "#1d4ed8",
            "TXT": "#475569"
        }.get(ext_upper, "#64748b")

        lbl_badge = QLabel(f" {ext_upper} ")
        lbl_badge.setStyleSheet(f"""
            background-color: {badge_color};
            color: white;
            font-size: 10px;
            font-weight: bold;
            border-radius: 4px;
            padding: 2px 4px;
        """)
        header_layout.addWidget(lbl_badge)

        lbl_title = QLabel(item.title)
        title_font = QFont()
        title_font.setPointSize(11)
        title_font.setBold(True)
        lbl_title.setFont(title_font)
        lbl_title.setStyleSheet("color: #0f172a;")
        header_layout.addWidget(lbl_title)
        header_layout.addStretch()

        btn_open = QPushButton("Open File")
        btn_open.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #e2e8f0;
            }
        """)
        btn_open.clicked.connect(lambda: open_file_externally(item.source_path))
        header_layout.addWidget(btn_open)

        layout.addLayout(header_layout)

        # Meta row: Page, paragraph, file path
        lbl_meta = QLabel(
            f"Page {item.page_number} • Paragraph {item.paragraph_number} • "
            f"File: {item.filename} • BM25 Rank: {item.rank_score:.2f}"
        )
        lbl_meta.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(lbl_meta)

        # Snippet with styled highlight
        styled_snippet = item.snippet.replace(
            "<mark>", "<span style='background-color: #fef08a; color: #854d0e; font-weight: bold; padding: 1px 3px; border-radius: 2px;'>"
        ).replace("</mark>", "</span>")

        lbl_snip = QLabel(styled_snippet)
        lbl_snip.setTextFormat(Qt.RichText)
        lbl_snip.setWordWrap(True)
        lbl_snip.setStyleSheet("color: #1e293b; font-size: 12px; line-height: 1.4;")
        layout.addWidget(lbl_snip)


class SearchTab(QWidget):
    """Interactive FTS5 Search interface for desktop."""

    def __init__(self, db_manager: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.current_page = 1
        self.page_size = 15
        self.last_query = ""

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 1. Search Bar
        search_box_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search medical literature (e.g. \"Left Main\", IVUS AND CTO, stent -thrombosis, litho*)...")
        self.search_input.setStyleSheet("""
            QLineEdit {
                padding: 10px 14px;
                font-size: 13px;
                border: 2px solid #cbd5e1;
                border-radius: 6px;
                background-color: #ffffff;
            }
            QLineEdit:focus {
                border-color: #2563eb;
            }
        """)
        self.search_input.returnPressed.connect(self._on_search)

        # Autocomplete model
        self.completer_model = QStringListModel()
        self.completer = QCompleter(self.completer_model, self)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.search_input.setCompleter(self.completer)
        self.search_input.textChanged.connect(self._on_text_changed)

        self.btn_search = QPushButton("Search")
        self.btn_search.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: white;
                font-weight: bold;
                font-size: 13px;
                padding: 10px 20px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
        """)
        self.btn_search.clicked.connect(self._on_search)

        search_box_layout.addWidget(self.search_input)
        search_box_layout.addWidget(self.btn_search)
        layout.addLayout(search_box_layout)

        # 2. Options and Filters Row
        opt_layout = QHBoxLayout()

        self.chk_synonyms = QCheckBox("Cardiology Synonym Expansion (LM ↔ Left Main, CTO ↔ Chronic Total Occlusion, etc.)")
        self.chk_synonyms.setChecked(True)
        opt_layout.addWidget(self.chk_synonyms)

        opt_layout.addSpacing(16)
        opt_layout.addWidget(QLabel("Filter:"))

        self.chk_pdf = QCheckBox("PDF")
        self.chk_pdf.setChecked(True)
        self.chk_docx = QCheckBox("DOCX")
        self.chk_docx.setChecked(True)
        self.chk_doc = QCheckBox("DOC")
        self.chk_doc.setChecked(True)
        self.chk_txt = QCheckBox("TXT")
        self.chk_txt.setChecked(True)

        opt_layout.addWidget(self.chk_pdf)
        opt_layout.addWidget(self.chk_docx)
        opt_layout.addWidget(self.chk_doc)
        opt_layout.addWidget(self.chk_txt)

        opt_layout.addStretch()

        self.btn_manage_synonyms = QPushButton("Manage Synonyms...")
        self.btn_manage_synonyms.clicked.connect(self._open_synonyms_dialog)
        opt_layout.addWidget(self.btn_manage_synonyms)

        layout.addLayout(opt_layout)

        # 3. Info Banner
        self.lbl_info = QLabel("Enter keywords, phrases, or Boolean operators to search.")
        self.lbl_info.setStyleSheet("color: #475569; font-size: 11px;")
        layout.addWidget(self.lbl_info)

        # 4. Results Scroll Area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea { border: 1px solid #e2e8f0; border-radius: 6px; background-color: #f8fafc; }")

        self.results_container = QWidget()
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setContentsMargins(12, 12, 12, 12)
        self.results_layout.setSpacing(6)
        self.results_layout.addStretch()

        self.scroll_area.setWidget(self.results_container)
        layout.addWidget(self.scroll_area, stretch=1)

        # 5. Pagination Controls
        pag_layout = QHBoxLayout()
        self.btn_prev = QPushButton("◀ Previous")
        self.btn_prev.setEnabled(False)
        self.btn_prev.clicked.connect(self._prev_page)

        self.lbl_page = QLabel("Page 1 of 1")
        self.lbl_page.setStyleSheet("font-weight: 600; color: #334155;")

        self.btn_next = QPushButton("Next ▶")
        self.btn_next.setEnabled(False)
        self.btn_next.clicked.connect(self._next_page)

        pag_layout.addWidget(self.btn_prev)
        pag_layout.addStretch()
        pag_layout.addWidget(self.lbl_page)
        pag_layout.addStretch()
        pag_layout.addWidget(self.btn_next)
        layout.addLayout(pag_layout)

    def _on_text_changed(self, text: str) -> None:
        """Fetch auto-complete suggestions dynamically as user types."""
        if len(text.strip()) >= 2:
            try:
                search_svc = self.db.get_search_service()
                sugs = search_svc.get_suggestions(text.strip(), limit=6)
                items = [s["display"] for s in sugs]
                self.completer_model.setStringList(items)
            except Exception:
                pass

    def _open_synonyms_dialog(self) -> None:
        dialog = SynonymsDialog(self.db.get_connection(), self)
        dialog.exec()

    def _get_active_extensions(self) -> Optional[List[str]]:
        exts = []
        if self.chk_pdf.isChecked():
            exts.append(".pdf")
        if self.chk_docx.isChecked():
            exts.append(".docx")
        if self.chk_doc.isChecked():
            exts.append(".doc")
        if self.chk_txt.isChecked():
            exts.append(".txt")
        # If all or none checked, return None (no filter)
        if len(exts) == 4 or len(exts) == 0:
            return None
        return exts

    def _on_search(self) -> None:
        self.current_page = 1
        self._execute_search()

    def _prev_page(self) -> None:
        if self.current_page > 1:
            self.current_page -= 1
            self._execute_search()

    def _next_page(self) -> None:
        self.current_page += 1
        self._execute_search()

    def _execute_search(self) -> None:
        query = self.search_input.text().strip()
        if not query:
            return

        search_svc = self.db.get_search_service()
        expand = self.chk_synonyms.isChecked()
        exts = self._get_active_extensions()

        res = search_svc.search(
            query=query,
            page=self.current_page,
            page_size=self.page_size,
            expand_synonyms=expand,
            extensions=exts
        )

        self._render_results(res)

    def _render_results(self, res: SearchResponse) -> None:
        # Clear existing result cards
        while self.results_layout.count() > 0:
            item = self.results_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        # Update info label
        info_parts = [f"Found <b>{res.total_count:,}</b> matching paragraphs in <b>{res.execution_time_ms:.1f} ms</b>."]
        if res.expanded_query:
            applied_str = ", ".join(f"<b>{t}</b> → <i>{exp}</i>" for t, exp in res.synonyms_applied)
            info_parts.append(f"<br><span style='color: #2563eb;'>Synonym expansion active: {applied_str}</span>")

        self.lbl_info.setText(" ".join(info_parts))

        # Add result cards
        if not res.items:
            lbl_empty = QLabel("No matching documents found. Try adjusting your search query or filters.")
            lbl_empty.setStyleSheet("color: #64748b; font-style: italic; padding: 20px;")
            lbl_empty.setAlignment(Qt.AlignCenter)
            self.results_layout.addWidget(lbl_empty)
        else:
            for item in res.items:
                card = ResultCard(item, self.results_container)
                self.results_layout.addWidget(card)

        self.results_layout.addStretch()

        # Update pagination controls
        self.lbl_page.setText(f"Page {res.page} of {max(res.total_pages, 1)}")
        self.btn_prev.setEnabled(res.page > 1)
        self.btn_next.setEnabled(res.page < res.total_pages)

        # Scroll to top
        self.scroll_area.verticalScrollBar().setValue(0)
