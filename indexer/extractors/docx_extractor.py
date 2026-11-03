"""DOCX document extractor using python-docx."""

from __future__ import annotations
import math
from pathlib import Path
from typing import List, Tuple

try:
    import docx
    from docx.oxml.text.paragraph import CT_P
    from docx.oxml.table import CT_Tbl
    from docx.text.paragraph import Paragraph
    from docx.table import Table
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False
    docx = None  # type: ignore
    CT_P = None  # type: ignore
    CT_Tbl = None  # type: ignore
    Paragraph = None  # type: ignore
    Table = None  # type: ignore

from .base import BaseExtractor
from ..models import ExtractedDocument, ExtractedPage, ExtractedParagraph, ExtractionStatus
from ..config import logger


class DocxExtractor(BaseExtractor):
    """Extractor for Microsoft Word .docx files."""

    def __init__(self):
        super().__init__({".docx"})

    def extract_content(self, file_path: Path, doc: ExtractedDocument) -> None:
        if not DOCX_AVAILABLE:
            doc.extraction_status = ExtractionStatus.ERROR.value
            doc.error_message = (
                "python-docx is not installed. Please run: pip install python-docx"
            )
            logger.warning(f"Failed to process {file_path}: {doc.error_message}")
            return

        docx_doc = docx.Document(str(file_path))

        # 1. Document Title
        title = ""
        try:
            core_props = docx_doc.core_properties
            if core_props.title and core_props.title.strip():
                title = core_props.title.strip()
        except Exception:
            pass

        # 2. Headers and Footers
        header_footer_texts: List[str] = []
        try:
            for section in docx_doc.sections:
                if section.header:
                    for p in section.header.paragraphs:
                        txt = p.text.strip()
                        if txt and txt not in header_footer_texts:
                            header_footer_texts.append(txt)
                if section.footer:
                    for p in section.footer.paragraphs:
                        txt = p.text.strip()
                        if txt and txt not in header_footer_texts:
                            header_footer_texts.append(txt)
        except Exception as e:
            logger.debug(f"Could not read headers/footers for {file_path}: {e}")

        # 3. Preserve visual order of paragraphs and tables by iterating through XML body
        raw_items: List[str] = []

        # Prepend header text if available
        for hf in header_footer_texts:
            raw_items.append(f"[Header/Footer] {hf}")

        for child in docx_doc.element.body:
            if isinstance(child, CT_P):
                p = Paragraph(child, docx_doc)
                text = p.text.strip()
                if text:
                    # Check for title style if not already found
                    if not title and p.style and p.style.name in ["Title", "Heading 1"]:
                        title = text
                    raw_items.append(text)
            elif isinstance(child, CT_Tbl):
                table = Table(child, docx_doc)
                table_lines = []
                for row in table.rows:
                    row_cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                    row_str = " | ".join(c for c in row_cells if c)
                    if row_str:
                        table_lines.append(row_str)
                if table_lines:
                    raw_items.append("[Table]\n" + "\n".join(table_lines))

        if not title and raw_items:
            title = raw_items[0][:100]
        doc.title = title or file_path.stem

        # 4. Map into pages and paragraphs (simulating ~2500 characters per page)
        doc_paragraphs: List[ExtractedParagraph] = []
        doc_pages: List[ExtractedPage] = []

        chars_per_page = 2500
        current_page_num = 1
        current_page_chars = 0
        current_page_paras: List[ExtractedParagraph] = []
        current_page_text_parts: List[str] = []

        for p_idx, text in enumerate(raw_items, start=1):
            para = ExtractedParagraph(
                page_number=current_page_num,
                paragraph_number=p_idx,
                text=text
            )
            doc_paragraphs.append(para)
            current_page_paras.append(para)
            current_page_text_parts.append(text)
            current_page_chars += len(text)

            # Move to next page if size threshold reached
            if current_page_chars >= chars_per_page and p_idx < len(raw_items):
                page_text = "\n\n".join(current_page_text_parts)
                doc_pages.append(ExtractedPage(
                    page_number=current_page_num,
                    text=page_text,
                    is_scanned=False,
                    paragraphs=list(current_page_paras)
                ))
                current_page_num += 1
                current_page_chars = 0
                current_page_paras.clear()
                current_page_text_parts.clear()

        # Final page flush
        if current_page_text_parts:
            page_text = "\n\n".join(current_page_text_parts)
            doc_pages.append(ExtractedPage(
                page_number=current_page_num,
                text=page_text,
                is_scanned=False,
                paragraphs=list(current_page_paras)
            ))

        doc.page_count = max(len(doc_pages), 1)
        doc.pages = doc_pages
        doc.paragraphs = doc_paragraphs
        doc.extraction_status = ExtractionStatus.INDEXED.value
