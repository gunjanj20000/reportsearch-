"""Dashboard widget displaying the 8 primary indexing metrics."""

from __future__ import annotations
from PySide6.QtWidgets import QWidget, QGridLayout, QLabel, QFrame, QVBoxLayout
from PySide6.QtCore import Qt

from ..models import DashboardStats


def format_bytes(num_bytes: int) -> str:
    """Format bytes into readable units."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    elif num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


class StatCard(QFrame):
    """Modern metric card with title and bold value."""

    def __init__(self, title: str, initial_value: str = "0", parent: QWidget | None = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("""
            StatCard {
                background-color: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                padding: 12px;
            }
            QLabel#title {
                color: #64748b;
                font-size: 12px;
                font-weight: 500;
            }
            QLabel#value {
                color: #0f172a;
                font-size: 20px;
                font-weight: 700;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(4)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("title")
        self.title_label.setWordWrap(True)

        self.value_label = QLabel(initial_value)
        self.value_label.setObjectName("value")

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)

    def set_value(self, val: str) -> None:
        self.value_label.setText(val)


class DashboardWidget(QWidget):
    """Grid of 8 statistical metric cards for indexing status."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        grid = QGridLayout(self)
        grid.setSpacing(12)
        grid.setContentsMargins(0, 0, 0, 0)

        # 8 required metrics from prompt Section 3
        self.card_total_docs = StatCard("Total Indexed Documents", "0")
        self.card_orig_size = StatCard("Total Original File Size", "0 B")
        self.card_extracted_size = StatCard("Extracted Text Size", "0 B")
        self.card_db_size = StatCard("Search Database Size", "0 B")
        self.card_pdf_pages = StatCard("Number of PDF Pages", "0")
        self.card_word_docs = StatCard("Number of Word Docs", "0")
        self.card_scanned_pdfs = StatCard("Number of Scanned PDFs", "0")
        self.card_last_indexed = StatCard("Last Indexing Date", "Never")

        # Row 0
        grid.addWidget(self.card_total_docs, 0, 0)
        grid.addWidget(self.card_orig_size, 0, 1)
        grid.addWidget(self.card_extracted_size, 0, 2)
        grid.addWidget(self.card_db_size, 0, 3)

        # Row 1
        grid.addWidget(self.card_pdf_pages, 1, 0)
        grid.addWidget(self.card_word_docs, 1, 1)
        grid.addWidget(self.card_scanned_pdfs, 1, 2)
        grid.addWidget(self.card_last_indexed, 1, 3)

    def update_stats(self, stats: DashboardStats) -> None:
        """Update all 8 cards with current stats."""
        self.card_total_docs.set_value(f"{stats.total_documents:,}")
        self.card_orig_size.set_value(format_bytes(stats.total_original_file_size))
        self.card_extracted_size.set_value(format_bytes(stats.extracted_text_size))
        self.card_db_size.set_value(format_bytes(stats.database_size))
        self.card_pdf_pages.set_value(f"{stats.number_of_pdf_pages:,}")
        self.card_word_docs.set_value(f"{stats.number_of_word_documents:,}")
        self.card_scanned_pdfs.set_value(f"{stats.number_of_scanned_pdfs:,}")
        self.card_last_indexed.set_value(stats.last_indexing_date or "Never")
