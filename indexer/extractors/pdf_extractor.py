"""PDF document extractor with scanned-page detection and Tesseract OCR."""

from __future__ import annotations
import io
import re
from pathlib import Path
from typing import List, Optional

import pymupdf
from PIL import Image

# CPU compatibility guard: pytesseract imports numpy if present, but crashes on older CPUs if numpy raises RuntimeError
try:
    import numpy
except Exception:
    import sys
    sys.modules["numpy"] = None

import pytesseract

from .base import BaseExtractor
from ..models import ExtractedDocument, ExtractedPage, ExtractedParagraph, ExtractionStatus
from ..config import logger, DEFAULT_OCR_LANGUAGES, MIN_TEXT_CHARS_FOR_NATIVE_PDF, find_tesseract_binary


class PdfExtractor(BaseExtractor):
    """Extractor for PDF documents supporting native text, scanned pages, and mixed PDFs."""

    def __init__(self, ocr_languages: str = DEFAULT_OCR_LANGUAGES):
        super().__init__({".pdf"})
        self.ocr_languages = ocr_languages
        tess_bin = find_tesseract_binary()
        if tess_bin:
            pytesseract.pytesseract.tesseract_cmd = tess_bin
        self.tesseract_available = tess_bin is not None

    def extract_content(self, file_path: Path, doc: ExtractedDocument) -> None:
        try:
            pdf = pymupdf.open(str(file_path))
        except Exception as e:
            doc.extraction_status = ExtractionStatus.ERROR.value
            doc.error_message = f"Failed to open PDF: {e}"
            logger.error(f"Error opening {file_path}: {e}")
            return

        doc.page_count = len(pdf)
        if doc.page_count == 0:
            doc.extraction_status = ExtractionStatus.INDEXED.value
            doc.title = file_path.stem
            return

        # Attempt to read PDF metadata title
        meta_title = ""
        try:
            meta = pdf.metadata or {}
            if meta.get("title") and meta["title"].strip():
                meta_title = meta["title"].strip()
        except Exception:
            pass

        scanned_page_count = 0
        all_pages: List[ExtractedPage] = []
        all_paragraphs: List[ExtractedParagraph] = []
        global_para_counter = 1
        first_meaningful_text = ""

        for page_idx in range(doc.page_count):
            page_num = page_idx + 1
            page = pdf[page_idx]

            # 1. Native text extraction via blocks (x0, y0, x1, y1, text, block_no, block_type)
            blocks = page.get_text("blocks")
            text_blocks = [b[4].strip() for b in blocks if len(b) > 4 and b[6] == 0 and b[4].strip()]
            native_text = "\n\n".join(text_blocks)
            char_count = sum(len(b) for b in text_blocks)

            # Check if page has images
            image_list = page.get_images(full=True)
            has_images = len(image_list) > 0

            # 2. Determine if page is scanned or image-dominant
            is_scanned = False
            if (char_count < MIN_TEXT_CHARS_FOR_NATIVE_PDF and has_images) or (char_count == 0):
                if self.tesseract_available:
                    logger.debug(f"Page {page_num} of {file_path.name} is scanned/image. Running OCR...")
                    try:
                        # If page contains embedded full image, extract directly for maximum fidelity
                        img = None
                        if has_images and len(image_list) == 1:
                            try:
                                xref = image_list[0][0]
                                base_image = pdf.extract_image(xref)
                                img = Image.open(io.BytesIO(base_image["image"]))
                            except Exception:
                                img = None

                        # Fallback to high-resolution page rendering
                        if img is None:
                            pix = page.get_pixmap(matrix=pymupdf.Matrix(2.0, 2.0))
                            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                        ocr_text = pytesseract.image_to_string(img, lang=self.ocr_languages)
                        ocr_cleaned = ocr_text.strip()
                        if ocr_cleaned:
                            is_scanned = True
                            scanned_page_count += 1
                            # Break into paragraphs by empty lines
                            raw_paras = [p.strip() for p in re.split(r"\n\s*\n", ocr_cleaned) if p.strip()]
                            page_paras: List[ExtractedParagraph] = []
                            for p_txt in raw_paras:
                                para_obj = ExtractedParagraph(
                                    page_number=page_num,
                                    paragraph_number=global_para_counter,
                                    text=p_txt
                                )
                                page_paras.append(para_obj)
                                all_paragraphs.append(para_obj)
                                global_para_counter += 1

                            all_pages.append(ExtractedPage(
                                page_number=page_num,
                                text=ocr_cleaned,
                                is_scanned=True,
                                paragraphs=page_paras
                            ))

                            if not first_meaningful_text and raw_paras:
                                first_meaningful_text = raw_paras[0][:120]
                            continue
                    except Exception as ocr_err:
                        logger.warning(f"OCR failed on page {page_num} of {file_path.name}: {ocr_err}")

            # 3. If native text or OCR fallback failed, use native text blocks
            page_paras: List[ExtractedParagraph] = []
            for b_txt in text_blocks:
                para_obj = ExtractedParagraph(
                    page_number=page_num,
                    paragraph_number=global_para_counter,
                    text=b_txt
                )
                page_paras.append(para_obj)
                all_paragraphs.append(para_obj)
                global_para_counter += 1

            all_pages.append(ExtractedPage(
                page_number=page_num,
                text=native_text,
                is_scanned=False,
                paragraphs=page_paras
            ))

            if not first_meaningful_text and text_blocks:
                first_meaningful_text = text_blocks[0][:120]

        pdf.close()

        # Set title
        doc.title = meta_title or first_meaningful_text or file_path.stem
        doc.pages = all_pages
        doc.paragraphs = all_paragraphs

        # Set status based on scanned page count
        if scanned_page_count == doc.page_count and doc.page_count > 0:
            doc.extraction_status = ExtractionStatus.SCANNED_OCR.value
        elif scanned_page_count > 0:
            doc.extraction_status = ExtractionStatus.MIXED.value
        else:
            doc.extraction_status = ExtractionStatus.INDEXED.value
