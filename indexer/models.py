"""Data structures and models for document extraction and indexing."""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class ExtractionStatus(str, Enum):
    INDEXED = "indexed"
    SCANNED_OCR = "scanned_ocr"
    MIXED = "mixed"
    ERROR = "error"
    UNSUPPORTED = "unsupported"


@dataclass
class ExtractedParagraph:
    page_number: int
    paragraph_number: int
    text: str


@dataclass
class ExtractedPage:
    page_number: int
    text: str
    is_scanned: bool = False
    paragraphs: List[ExtractedParagraph] = field(default_factory=list)


@dataclass
class ExtractedDocument:
    filename: str
    extension: str
    file_size: int
    modified_time: float
    sha256: str
    source_path: str
    title: str = ""
    page_count: int = 0
    extraction_status: str = ExtractionStatus.INDEXED.value
    error_message: Optional[str] = None
    pages: List[ExtractedPage] = field(default_factory=list)
    paragraphs: List[ExtractedParagraph] = field(default_factory=list)
    google_drive_file_id: Optional[str] = None
    google_drive_url: Optional[str] = None

    @property
    def total_extracted_chars(self) -> int:
        return sum(len(p.text) for p in self.paragraphs) or sum(len(pg.text) for pg in self.pages)


@dataclass
class DashboardStats:
    total_documents: int = 0
    total_original_file_size: int = 0
    extracted_text_size: int = 0
    database_size: int = 0
    number_of_pdf_pages: int = 0
    number_of_word_documents: int = 0
    number_of_scanned_pdfs: int = 0
    indexing_progress: float = 0.0
    last_indexing_date: Optional[str] = None
