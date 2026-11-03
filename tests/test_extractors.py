"""Automated tests for document extractors using self-contained dynamic fixtures."""

import tempfile
from pathlib import Path
import pytest
from PIL import Image, ImageDraw

from indexer.extractors.factory import default_factory
from indexer.extractors.docx_extractor import DocxExtractor
from indexer.extractors.doc_extractor import DocExtractor
from indexer.extractors.pdf_extractor import PdfExtractor
from indexer.extractors.txt_extractor import TxtExtractor
from indexer.models import ExtractionStatus

try:
    import docx
    DOCX_INSTALLED = True
except ImportError:
    docx = None
    DOCX_INSTALLED = False

try:
    import pymupdf
    PYMUPDF_INSTALLED = True
except ImportError:
    pymupdf = None
    PYMUPDF_INSTALLED = False


@pytest.fixture(scope="module")
def extractor_fixtures(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("extractor_fixtures")
    fixtures = {}

    # 1. DOCX with table
    if DOCX_INSTALLED:
        d = docx.Document()
        d.add_heading("Left Main Coronary Trial", level=1)
        d.add_paragraph("Left Main (LM) revascularization clinical trial report.")
        tbl = d.add_table(rows=2, cols=2)
        tbl.cell(0, 0).text = "Variable"
        tbl.cell(0, 1).text = "Result"
        tbl.cell(1, 0).text = "MLA"
        tbl.cell(1, 1).text = "6.0 mm2"
        docx_p = tmp / "test_trial.docx"
        d.save(docx_p)
        fixtures["docx"] = docx_p

        # Hindi DOCX
        hd = docx.Document()
        hd.add_paragraph("हृदय रोग और कोरोनरी धमनी उपचार दिशानिर्देश")
        hdocx_p = tmp / "hindi_trial.docx"
        hd.save(hdocx_p)
        fixtures["hindi_docx"] = hdocx_p

    # 2. Native PDF (2 pages)
    if PYMUPDF_INSTALLED:
        pdf = pymupdf.open()
        p1 = pdf.new_page()
        p1.insert_text((50, 50), "European Cardiology Guidelines for CTO Revascularization.\nSection 1: Introduction.")
        p2 = pdf.new_page()
        p2.insert_text((50, 50), "Section 2: Procedural considerations and IVUS imaging.")
        pdf_p = tmp / "test_guideline.pdf"
        pdf.save(pdf_p)
        pdf.close()
        fixtures["pdf"] = pdf_p

        # Scanned PDF (with image text)
        img = Image.new("RGB", (600, 200), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.text((20, 40), "CATH LAB REPORT - CORONARY IVUS STENT", fill=(0, 0, 0))
        img_p = tmp / "scanned_img.png"
        img.save(img_p)

        pdf_scanned = pymupdf.open()
        sp = pdf_scanned.new_page(width=600, height=200)
        sp.insert_image(pymupdf.Rect(0, 0, 600, 200), filename=str(img_p))
        scanned_p = tmp / "scanned_report.pdf"
        pdf_scanned.save(scanned_p)
        pdf_scanned.close()
        fixtures["scanned_pdf"] = scanned_p

        # Mixed PDF (page 1 text, page 2 image)
        pdf_mixed = pymupdf.open()
        mp1 = pdf_mixed.new_page(width=600, height=200)
        mp1.insert_text((50, 50), "Mixed document page 1 with digital text for testing.")
        mp2 = pdf_mixed.new_page(width=600, height=200)
        mp2.insert_image(pymupdf.Rect(0, 0, 600, 200), filename=str(img_p))
        mixed_p = tmp / "mixed_report.pdf"
        pdf_mixed.save(mixed_p)
        pdf_mixed.close()
        fixtures["mixed_pdf"] = mixed_p

        # Hindi PDF
        hpdf = pymupdf.open()
        hp = hpdf.new_page()
        hp.insert_text((50, 50), "हृदय रोग और कोरोनरी धमनी उपचार दिशानिर्देश")
        hpdf_p = tmp / "hindi_trial.pdf"
        hpdf.save(hpdf_p)
        hpdf.close()
        fixtures["hindi_pdf"] = hpdf_p

    # 3. TXT
    txt_p = tmp / "discharge_summary.txt"
    txt_p.write_text("DISCHARGE SUMMARY\nPatient treated for acute coronary syndrome with DES.")
    fixtures["txt"] = txt_p

    # 4. Corrupted
    bad_pdf = tmp / "bad.pdf"
    bad_pdf.write_bytes(b"%PDF-1.4\nTRUNCATED_BAD_BYTES")
    bad_docx = tmp / "bad.docx"
    bad_docx.write_bytes(b"NOT_A_ZIP_ARCHIVE")
    fixtures["corrupted"] = [bad_pdf, bad_docx]

    return fixtures


def test_docx_extractor(extractor_fixtures):
    if "docx" not in extractor_fixtures:
        pytest.skip("python-docx not installed")

    extractor = DocxExtractor()
    doc = extractor.extract(extractor_fixtures["docx"])

    assert doc.extraction_status == ExtractionStatus.INDEXED.value
    assert doc.title != ""
    assert doc.page_count >= 1
    assert len(doc.paragraphs) > 0
    assert len(doc.pages) >= 1
    # Check that table text was extracted
    table_paras = [p for p in doc.paragraphs if "[Table]" in p.text or "|" in p.text]
    assert len(table_paras) > 0, "Tables should be extracted and preserved"


def test_docx_table_merged_cells_deduplication(tmp_path):
    """Ensure merged cells in DOCX tables are not duplicated across grid columns."""
    try:
        import docx
    except ImportError:
        pytest.skip("python-docx not installed")

    doc = docx.Document()
    doc.add_heading("Angiography Report", level=1)
    table = doc.add_table(rows=2, cols=6)

    # Merged horizontal cells (e.g. name across cols 1-2, age label across cols 3-4)
    table.cell(0, 0).text = "NAME :"
    table.cell(0, 1).merge(table.cell(0, 2))
    table.cell(0, 1).text = "Mr.ARJUN LAL"
    table.cell(0, 3).merge(table.cell(0, 4))
    table.cell(0, 3).text = "AGE :"
    table.cell(0, 5).text = "58Years"

    # Row 1: Doctor operator across 5 columns
    table.cell(1, 0).text = "OPERATOR:"
    c1 = table.cell(1, 1)
    for i in range(2, 6):
        c1.merge(table.cell(1, i))
    c1.text = "Dr. Prakash Chandwani / Dr. Divij Khetan"

    test_file = tmp_path / "test_merged_table.docx"
    doc.save(str(test_file))

    extractor = DocxExtractor()
    extracted = extractor.extract(test_file)

    assert extracted.extraction_status == ExtractionStatus.INDEXED.value
    table_paras = [p.text for p in extracted.paragraphs if "[Table]" in p.text]
    assert len(table_paras) == 1
    table_text = table_paras[0]

    # Verify no duplicate entries in extracted table lines
    lines = [l for l in table_text.splitlines() if l != "[Table]"]
    assert len(lines) == 2

    # Line 0 check: NAME : | Mr.ARJUN LAL | AGE : | 58Years
    cells_row0 = [c.strip() for c in lines[0].split("|")]
    assert cells_row0 == ["NAME :", "Mr.ARJUN LAL", "AGE :", "58Years"]
    assert cells_row0.count("Mr.ARJUN LAL") == 1
    assert cells_row0.count("AGE :") == 1

    # Line 1 check: OPERATOR: | Dr. Prakash Chandwani / Dr. Divij Khetan (only once, not 5 times!)
    cells_row1 = [c.strip() for c in lines[1].split("|")]
    assert cells_row1 == ["OPERATOR:", "Dr. Prakash Chandwani / Dr. Divij Khetan"]
    assert cells_row1.count("Dr. Prakash Chandwani / Dr. Divij Khetan") == 1


def test_native_pdf_extractor(extractor_fixtures):
    if "pdf" not in extractor_fixtures:
        pytest.skip("pymupdf not installed")

    extractor = PdfExtractor()
    doc = extractor.extract(extractor_fixtures["pdf"])

    assert doc.extraction_status == ExtractionStatus.INDEXED.value
    assert doc.page_count >= 2
    assert len(doc.pages) == doc.page_count
    assert len(doc.paragraphs) > 0
    assert doc.title != ""


def test_scanned_pdf_ocr(extractor_fixtures):
    if "scanned_pdf" not in extractor_fixtures:
        pytest.skip("pymupdf not installed")

    extractor = PdfExtractor()
    doc = extractor.extract(extractor_fixtures["scanned_pdf"])

    assert doc.extraction_status in [ExtractionStatus.SCANNED_OCR.value, ExtractionStatus.INDEXED.value]
    assert doc.page_count == 1
    assert len(doc.paragraphs) > 0


def test_mixed_pdf_extractor(extractor_fixtures):
    if "mixed_pdf" not in extractor_fixtures:
        pytest.skip("pymupdf not installed")

    extractor = PdfExtractor()
    doc = extractor.extract(extractor_fixtures["mixed_pdf"])

    assert doc.extraction_status in [ExtractionStatus.MIXED.value, ExtractionStatus.INDEXED.value]
    assert doc.page_count == 2


def test_hindi_multilingual_extraction(extractor_fixtures):
    if "hindi_docx" in extractor_fixtures:
        doc_docx = default_factory.extract(extractor_fixtures["hindi_docx"])
        assert doc_docx.extraction_status == ExtractionStatus.INDEXED.value
        full_docx_text = " ".join(p.text for p in doc_docx.paragraphs)
        assert any(word in full_docx_text for word in ["धमनी", "हृदय", "कोरोनरी"])

    if "hindi_pdf" in extractor_fixtures:
        doc_pdf = default_factory.extract(extractor_fixtures["hindi_pdf"])
        assert doc_pdf.extraction_status == ExtractionStatus.INDEXED.value


def test_txt_extractor(extractor_fixtures):
    extractor = TxtExtractor()
    doc = extractor.extract(extractor_fixtures["txt"])

    assert doc.extraction_status == ExtractionStatus.INDEXED.value
    assert doc.page_count >= 1
    assert len(doc.paragraphs) > 0
    assert "DISCHARGE SUMMARY" in doc.paragraphs[0].text


def test_corrupted_files_graceful_handling(extractor_fixtures):
    for bad_file in extractor_fixtures["corrupted"]:
        doc = default_factory.extract(bad_file)
        assert doc.extraction_status in [ExtractionStatus.ERROR.value, ExtractionStatus.INDEXED.value]
        if doc.extraction_status == ExtractionStatus.ERROR.value:
            assert doc.error_message is not None


def test_docx_extractor_fallback_when_dependency_missing(extractor_fixtures, monkeypatch):
    if "docx" not in extractor_fixtures:
        pytest.skip("python-docx not installed")

    from indexer.extractors import docx_extractor
    monkeypatch.setattr(docx_extractor, "DOCX_AVAILABLE", False)

    extractor = DocxExtractor()
    doc = extractor.extract(extractor_fixtures["docx"])
    assert doc.extraction_status == ExtractionStatus.ERROR.value
    assert "python-docx" in doc.error_message


def test_pdf_extractor_fallback_when_dependency_missing(extractor_fixtures, monkeypatch):
    if "pdf" not in extractor_fixtures:
        pytest.skip("pymupdf not installed")

    from indexer.extractors import pdf_extractor
    monkeypatch.setattr(pdf_extractor, "PYMUPDF_AVAILABLE", False)

    extractor = PdfExtractor()
    doc = extractor.extract(extractor_fixtures["pdf"])
    assert doc.extraction_status == ExtractionStatus.ERROR.value
    assert "pymupdf" in doc.error_message
