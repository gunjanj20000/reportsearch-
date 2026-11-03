"""Base extractor interface and utility functions."""

from __future__ import annotations
import abc
import hashlib
import os
from pathlib import Path

from ..models import ExtractedDocument, ExtractionStatus
from ..config import logger


def calculate_sha256(file_path: Path | str, chunk_size: int = 65536) -> str:
    """Calculate SHA-256 hash of a file efficiently using streaming chunks."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


class BaseExtractor(abc.ABC):
    """Abstract base class for all file format extractors."""

    def __init__(self, supported_extensions: set[str]):
        self.supported_extensions = {ext.lower() for ext in supported_extensions}

    def can_handle(self, file_path: Path | str) -> bool:
        ext = Path(file_path).suffix.lower()
        return ext in self.supported_extensions

    def get_initial_metadata(self, file_path: Path | str) -> ExtractedDocument:
        """Create an ExtractedDocument with initial filesystem metadata."""
        path = Path(file_path).resolve()
        stat = path.stat()
        sha256 = calculate_sha256(path)

        return ExtractedDocument(
            filename=path.name,
            extension=path.suffix.lower(),
            file_size=stat.st_size,
            modified_time=stat.st_mtime,
            sha256=sha256,
            source_path=str(path),
            title=path.stem,
            page_count=0,
            extraction_status=ExtractionStatus.INDEXED.value,
            pages=[],
            paragraphs=[]
        )

    @abc.abstractmethod
    def extract_content(self, file_path: Path, doc: ExtractedDocument) -> None:
        """Extract pages, paragraphs, title, and metadata into doc."""
        pass

    def extract(self, file_path: Path | str) -> ExtractedDocument:
        """Execute full extraction with error handling."""
        path = Path(file_path).resolve()
        if not path.is_file():
            return ExtractedDocument(
                filename=path.name,
                extension=path.suffix.lower(),
                file_size=0,
                modified_time=0.0,
                sha256="",
                source_path=str(path),
                extraction_status=ExtractionStatus.ERROR.value,
                error_message=f"File not found: {path}"
            )

        doc = self.get_initial_metadata(path)

        try:
            self.extract_content(path, doc)
        except Exception as e:
            logger.error(f"Error extracting {path}: {e}", exc_info=True)
            doc.extraction_status = ExtractionStatus.ERROR.value
            doc.error_message = str(e)

        return doc
