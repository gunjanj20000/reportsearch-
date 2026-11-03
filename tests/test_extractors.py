"""Automated tests for document extractors."""

from pathlib import Path
import pytest

from indexer.extractors.factory import default_factory
from indexer.extractors.docx_extractor import DocxExtractor
from indexer.extractors.doc_extractor import DocExtractor
from indexer.extractors.pdf_extractor import PdfExtractor
from indexer.extractors.txt_extractor import TxtExtractor
from indexer.models import ExtractionStatus

CORPUS_DIR = Path("/home/ubuntu/searchengine/sample_corpus")


def test_docx_extractor():
    docx_files = list((CORPUS_DIR / "docx_trials").glob("*.docx"))
    assert len(docx_files) > 0, "No sample DOCX files found"

    sample = docx_files[0]
    extractor = DocxExtractor()
    doc = extractor.extract(sample)

    assert doc.extraction_status == ExtractionStatus.INDEXED.value
    assert doc.title != ""
    assert doc.page_count >= 1
    assert len(doc.paragraphs) > 0
    assert len(doc.pages) >= 1
    # Check that table text was extracted
    table_paras = [p for p in doc.paragraphs if "[Table]" in p.text or "|" in p.text]
    assert len(table_paras) > 0, "Tables should be extracted and preserved"


def test_legacy_doc_extractor():
    doc_files = list((CORPUS_DIR / "legacy_doc").glob("*.doc"))
    assert len(doc_files) > 0, "No sample DOC files found"

    sample = doc_files[0]
    extractor = DocExtractor()
    doc = extractor.extract(sample)

    assert doc.extraction_status == ExtractionStatus.INDEXED.value
    assert doc.title != ""
    assert len(doc.paragraphs) > 0
    # Must contain medical terminology from historical archive
    all_text = " ".join(p.text for p in doc.paragraphs)
    assert any(term in all_text for term in ["Historical", "BMS", "angioplasty", "registry", "Legacy"])


def test_native_pdf_extractor():
    pdf_files = list((CORPUS_DIR / "pdf_guidelines").glob("*.pdf"))
    assert len(pdf_files) > 0, "No sample PDF files found"

    sample = pdf_files[0]
    extractor = PdfExtractor()
    doc = extractor.extract(sample)

    assert doc.extraction_status == ExtractionStatus.INDEXED.value
    assert doc.page_count >= 2
    assert len(doc.pages) == doc.page_count
    assert len(doc.paragraphs) > 0
    assert doc.title != ""


def test_scanned_pdf_ocr():
    scanned_files = list((CORPUS_DIR / "scanned_pdf").glob("*.pdf"))
    assert len(scanned_files) > 0, "No sample scanned PDF files found"

    sample = scanned_files[0]
    extractor = PdfExtractor()
    doc = extractor.extract(sample)

    assert doc.extraction_status == ExtractionStatus.SCANNED_OCR.value
    assert doc.page_count == 1
    assert len(doc.paragraphs) > 0
    full_text = " ".join(p.text for p in doc.paragraphs).lower()
    # Check that OCR recognized cardiology cath lab terms
    assert any(w in full_text for w in ["cath", "lab", "coronary", "hospital", "ivus", "stent", "angiogram"])


def test_mixed_pdf_extractor():
    mixed_files = list((CORPUS_DIR / "mixed_pdf").glob("*.pdf"))
    assert len(mixed_files) > 0, "No sample mixed PDF files found"

    sample = mixed_files[0]
    extractor = PdfExtractor()
    doc = extractor.extract(sample)

    assert doc.extraction_status == ExtractionStatus.MIXED.value
    assert doc.page_count == 2
    assert doc.pages[0].is_scanned is False
    assert doc.pages[1].is_scanned is True


def test_hindi_multilingual_extraction():
    hindi_docx = list((CORPUS_DIR / "hindi_literature").glob("*.docx"))[0]
    doc_docx = default_factory.extract(hindi_docx)
    assert doc_docx.extraction_status == ExtractionStatus.INDEXED.value
    full_docx_text = " ".join(p.text for p in doc_docx.paragraphs)
    assert "धमनी" in full_docx_text or "हृदय" in full_docx_text or "कोरोनरी" in full_docx_text

    hindi_pdf = list((CORPUS_DIR / "hindi_literature").glob("*.pdf"))[0]
    doc_pdf = default_factory.extract(hindi_pdf)
    assert doc_pdf.extraction_status == ExtractionStatus.INDEXED.value
    full_pdf_text = " ".join(p.text for p in doc_pdf.paragraphs)
    assert "धमनी" in full_pdf_text or "हृदय" in full_pdf_text or "कोरोनरी" in full_pdf_text


def test_txt_extractor():
    txt_files = list((CORPUS_DIR / "txt_summaries").glob("*.txt"))
    assert len(txt_files) > 0, "No sample TXT files found"

    sample = txt_files[0]
    extractor = TxtExtractor()
    doc = extractor.extract(sample)

    assert doc.extraction_status == ExtractionStatus.INDEXED.value
    assert doc.page_count >= 1
    assert len(doc.paragraphs) > 0
    assert "DISCHARGE SUMMARY" in doc.paragraphs[0].text or "Case" in doc.paragraphs[0].text


def test_corrupted_files_graceful_handling():
    corrupted_files = list((CORPUS_DIR / "corrupted").glob("*.*"))
    assert len(corrupted_files) >= 4, "No corrupted sample files found"

    for bad_file in corrupted_files:
        doc = default_factory.extract(bad_file)
        # Should record error without crashing
        assert doc.extraction_status in [ExtractionStatus.ERROR.value, ExtractionStatus.INDEXED.value]
        if doc.extraction_status == ExtractionStatus.ERROR.value:
            assert doc.error_message is not None
            assert len(doc.error_message) > 0


def test_docx_extractor_fallback_when_dependency_missing(monkeypatch):
    from indexer.extractors import docx_extractor
    monkeypatch.setattr(docx_extractor, "DOCX_AVAILABLE", False)

    docx_files = list((CORPUS_DIR / "docx_trials").glob("*.docx"))
    assert len(docx_files) > 0

    extractor = DocxExtractor()
    doc = extractor.extract(docx_files[0])
    assert doc.extraction_status == ExtractionStatus.ERROR.value
    assert "python-docx" in doc.error_message


def test_pdf_extractor_fallback_when_dependency_missing(monkeypatch):
    from indexer.extractors import pdf_extractor
    monkeypatch.setattr(pdf_extractor, "PYMUPDF_AVAILABLE", False)

    pdf_files = list((CORPUS_DIR / "pdf_guidelines").glob("*.pdf"))
    assert len(pdf_files) > 0

    extractor = PdfExtractor()
    doc = extractor.extract(pdf_files[0])
    assert doc.extraction_status == ExtractionStatus.ERROR.value
    assert "pymupdf" in doc.error_message

