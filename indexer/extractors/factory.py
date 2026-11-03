"""Extractor factory to route files to the correct extractor."""

from __future__ import annotations
from pathlib import Path
from typing import Dict, Optional

from .base import BaseExtractor
from .docx_extractor import DocxExtractor
from .doc_extractor import DocExtractor
from .pdf_extractor import PdfExtractor
from .txt_extractor import TxtExtractor
from ..models import ExtractedDocument, ExtractionStatus


class ExtractorFactory:
    """Registry and factory for document extractors."""

    def __init__(self):
        self._extractors: Dict[str, BaseExtractor] = {}
        self.register(DocxExtractor())
        self.register(DocExtractor())
        self.register(PdfExtractor())
        self.register(TxtExtractor())

    def register(self, extractor: BaseExtractor) -> None:
        for ext in extractor.supported_extensions:
            self._extractors[ext.lower()] = extractor

    def get_extractor(self, file_path: Path | str) -> Optional[BaseExtractor]:
        ext = Path(file_path).suffix.lower()
        return self._extractors.get(ext)

    def extract(self, file_path: Path | str) -> ExtractedDocument:
        extractor = self.get_extractor(file_path)
        path = Path(file_path)
        if not extractor:
            return ExtractedDocument(
                filename=path.name,
                extension=path.suffix.lower(),
                file_size=path.stat().st_size if path.exists() else 0,
                modified_time=path.stat().st_mtime if path.exists() else 0.0,
                sha256="",
                source_path=str(path.resolve()),
                extraction_status=ExtractionStatus.UNSUPPORTED.value,
                error_message=f"Unsupported file format: {path.suffix}"
            )
        return extractor.extract(path)

# Default global factory instance
default_factory = ExtractorFactory()
