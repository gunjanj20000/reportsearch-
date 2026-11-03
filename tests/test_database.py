"""Automated tests for SQLite database and FTS5 search index."""

import tempfile
from pathlib import Path
import pytest

from indexer.database.connection import DatabaseManager
from indexer.models import ExtractedDocument, ExtractedPage, ExtractedParagraph, ExtractionStatus


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_medsearch.db"
        manager = DatabaseManager(db_path)
        yield manager
        manager.close()


def test_schema_initialization(temp_db):
    conn = temp_db.get_connection()
    tables = [
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    assert "documents" in tables
    assert "document_pages" in tables
    assert "document_paragraphs" in tables
    assert "collections" in tables
    assert "document_collections" in tables
    assert "search_index" in tables


def test_save_and_retrieve_document(temp_db):
    doc = ExtractedDocument(
        filename="test_ivus_study.pdf",
        extension=".pdf",
        file_size=102400,
        modified_time=1700000000.0,
        sha256="abcdef1234567890",
        source_path="/medical/docs/test_ivus_study.pdf",
        title="IVUS in Bifurcation Lesions",
        page_count=2,
        extraction_status=ExtractionStatus.INDEXED.value,
        pages=[
            ExtractedPage(page_number=1, text="Page 1: Left Main and IVUS criteria.", is_scanned=False),
            ExtractedPage(page_number=2, text="Page 2: Chronic total occlusion outcomes.", is_scanned=False),
        ],
        paragraphs=[
            ExtractedParagraph(page_number=1, paragraph_number=1, text="Left Main and IVUS criteria."),
            ExtractedParagraph(page_number=2, paragraph_number=2, text="Chronic total occlusion outcomes."),
        ]
    )

    doc_id = temp_db.save_document(doc)
    assert doc_id > 0

    retrieved = temp_db.get_document_by_path("/medical/docs/test_ivus_study.pdf")
    assert retrieved is not None
    assert retrieved["filename"] == "test_ivus_study.pdf"
    assert retrieved["page_count"] == 2
    assert retrieved["sha256"] == "abcdef1234567890"

    # Test FTS5 search
    conn = temp_db.get_connection()
    fts_rows = conn.execute(
        "SELECT * FROM search_index WHERE search_index MATCH 'bifurcation OR ivus'"
    ).fetchall()
    assert len(fts_rows) >= 1
    assert fts_rows[0]["document_id"] == doc_id


def test_dashboard_stats_calculation(temp_db):
    # Empty DB stats
    empty_stats = temp_db.get_dashboard_stats()
    assert empty_stats.total_documents == 0
    assert empty_stats.total_original_file_size == 0
    assert empty_stats.number_of_pdf_pages == 0
    assert empty_stats.number_of_word_documents == 0

    # Add 1 PDF document
    doc_pdf = ExtractedDocument(
        filename="cardio_guideline.pdf",
        extension=".pdf",
        file_size=50000,
        modified_time=1700000000.0,
        sha256="hash1",
        source_path="/docs/cardio_guideline.pdf",
        page_count=5,
        extraction_status=ExtractionStatus.INDEXED.value,
        pages=[ExtractedPage(page_number=i, text=f"Text for page {i}") for i in range(1, 6)],
        paragraphs=[ExtractedParagraph(page_number=1, paragraph_number=1, text="Cardio guideline text")]
    )
    temp_db.save_document(doc_pdf)

    # Add 1 Word document
    doc_word = ExtractedDocument(
        filename="trial_protocol.docx",
        extension=".docx",
        file_size=25000,
        modified_time=1700000000.0,
        sha256="hash2",
        source_path="/docs/trial_protocol.docx",
        page_count=1,
        extraction_status=ExtractionStatus.INDEXED.value,
        pages=[ExtractedPage(page_number=1, text="Word trial protocol")],
        paragraphs=[ExtractedParagraph(page_number=1, paragraph_number=1, text="Word trial protocol")]
    )
    temp_db.save_document(doc_word)

    # Check stats
    stats = temp_db.get_dashboard_stats()
    assert stats.total_documents == 2
    assert stats.total_original_file_size == 75000
    assert stats.number_of_pdf_pages == 5
    assert stats.number_of_word_documents == 1
    assert stats.number_of_scanned_pdfs == 0
    assert stats.database_size > 0
    assert stats.last_indexing_date is not None


def test_delete_document_and_cascades(temp_db):
    doc = ExtractedDocument(
        filename="to_delete.pdf",
        extension=".pdf",
        file_size=1000,
        modified_time=1700000000.0,
        sha256="hash_del",
        source_path="/docs/to_delete.pdf",
        page_count=1,
        pages=[ExtractedPage(page_number=1, text="Temporary text")],
        paragraphs=[ExtractedParagraph(page_number=1, paragraph_number=1, text="Temporary text")]
    )
    doc_id = temp_db.save_document(doc)

    conn = temp_db.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM document_pages WHERE document_id = ?", (doc_id,)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM search_index WHERE document_id = ?", (doc_id,)).fetchone()[0] == 1

    # Delete
    deleted = temp_db.delete_document_by_path("/docs/to_delete.pdf")
    assert deleted is True

    # Ensure cascades removed pages, paragraphs, and FTS
    assert conn.execute("SELECT COUNT(*) FROM document_pages WHERE document_id = ?", (doc_id,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM search_index WHERE document_id = ?", (doc_id,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM documents WHERE document_id = ?", (doc_id,)).fetchone()[0] == 0
