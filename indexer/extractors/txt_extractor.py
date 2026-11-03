"""Plain text file extractor with encoding autodetection."""

from __future__ import annotations
import re
from pathlib import Path
from typing import List

from .base import BaseExtractor
from ..models import ExtractedDocument, ExtractedPage, ExtractedParagraph, ExtractionStatus


class TxtExtractor(BaseExtractor):
    """Extractor for plain text (.txt) documents."""

    def __init__(self):
        super().__init__({".txt"})

    def extract_content(self, file_path: Path, doc: ExtractedDocument) -> None:
        encodings = ["utf-8", "utf-8-sig", "utf-16", "cp1252", "latin-1"]
        raw_text = ""

        with open(file_path, "rb") as f:
            data = f.read()

        for enc in encodings:
            try:
                raw_text = data.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue

        if not raw_text and data:
            raw_text = data.decode("utf-8", errors="replace")

        # Split into paragraphs by blank lines
        raw_paras = [p.strip() for p in re.split(r"\n\s*\n", raw_text) if p.strip()]

        paragraphs: List[ExtractedParagraph] = []
        pages: List[ExtractedPage] = []

        chars_per_page = 2500
        current_page = 1
        current_chars = 0
        current_paras: List[ExtractedParagraph] = []
        current_text_parts: List[str] = []

        for p_idx, p_text in enumerate(raw_paras, start=1):
            para = ExtractedParagraph(page_number=current_page, paragraph_number=p_idx, text=p_text)
            paragraphs.append(para)
            current_paras.append(para)
            current_text_parts.append(p_text)
            current_chars += len(p_text)

            if current_chars >= chars_per_page and p_idx < len(raw_paras):
                pages.append(ExtractedPage(
                    page_number=current_page,
                    text="\n\n".join(current_text_parts),
                    is_scanned=False,
                    paragraphs=list(current_paras)
                ))
                current_page += 1
                current_chars = 0
                current_paras.clear()
                current_text_parts.clear()

        if current_text_parts:
            pages.append(ExtractedPage(
                page_number=current_page,
                text="\n\n".join(current_text_parts),
                is_scanned=False,
                paragraphs=list(current_paras)
            ))

        doc.title = raw_paras[0][:100] if raw_paras else file_path.stem
        doc.page_count = max(len(pages), 1)
        doc.pages = pages
        doc.paragraphs = paragraphs
        doc.extraction_status = ExtractionStatus.INDEXED.value
