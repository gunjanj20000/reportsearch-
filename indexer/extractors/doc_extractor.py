"""Legacy DOC extractor using LibreOffice headless conversion."""

from __future__ import annotations
import subprocess
import tempfile
from pathlib import Path

from .base import BaseExtractor
from .docx_extractor import DocxExtractor
from ..models import ExtractedDocument, ExtractedPage, ExtractedParagraph, ExtractionStatus
from ..config import logger, find_libreoffice_binary


class DocExtractor(BaseExtractor):
    """Extractor for legacy Microsoft Word 97-2003 .doc files using LibreOffice headless."""

    def __init__(self):
        super().__init__({".doc"})
        self.docx_extractor = DocxExtractor()

    def extract_content(self, file_path: Path, doc: ExtractedDocument) -> None:
        lo_bin = find_libreoffice_binary()
        if not lo_bin:
            doc.extraction_status = ExtractionStatus.ERROR.value
            doc.error_message = (
                "LibreOffice binary not found. Legacy .doc conversion requires LibreOffice. "
                "Please install LibreOffice and ensure it is in PATH or set LIBREOFFICE_PATH."
            )
            logger.warning(f"Failed to process {file_path}: {doc.error_message}")
            return

        with tempfile.TemporaryDirectory(prefix="medsearch_doc_") as temp_dir:
            temp_path = Path(temp_dir)

            # 1. Attempt conversion to DOCX first to preserve full structure, tables, and headings
            cmd_docx = [
                lo_bin,
                "--headless",
                "--convert-to", "docx",
                str(file_path),
                "--outdir", str(temp_path)
            ]

            logger.info(f"Converting legacy .doc to .docx: {file_path.name}")
            try:
                proc = subprocess.run(
                    cmd_docx,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=90,
                    check=False
                )
            except subprocess.TimeoutExpired:
                doc.extraction_status = ExtractionStatus.ERROR.value
                doc.error_message = "LibreOffice conversion to DOCX timed out after 90 seconds."
                return

            converted_docx = temp_path / (file_path.stem + ".docx")
            if converted_docx.exists() and converted_docx.stat().st_size > 0:
                # Delegate to DocxExtractor
                sub_doc = self.docx_extractor.extract(converted_docx)
                if sub_doc.extraction_status == ExtractionStatus.INDEXED.value:
                    doc.title = sub_doc.title
                    doc.page_count = sub_doc.page_count
                    doc.pages = sub_doc.pages
                    doc.paragraphs = sub_doc.paragraphs
                    doc.extraction_status = ExtractionStatus.INDEXED.value
                    return
                else:
                    logger.warning(f"DocxExtractor failed on converted file: {sub_doc.error_message}")

            # 2. Fallback: attempt direct conversion to plain text
            logger.info(f"Fallback: converting .doc directly to plain text: {file_path.name}")
            cmd_txt = [
                lo_bin,
                "--headless",
                "--convert-to", "txt:Text",
                str(file_path),
                "--outdir", str(temp_path)
            ]
            try:
                proc_txt = subprocess.run(
                    cmd_txt,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=60,
                    check=False
                )
            except subprocess.TimeoutExpired:
                doc.extraction_status = ExtractionStatus.ERROR.value
                doc.error_message = "LibreOffice conversion to text timed out."
                return

            converted_txt = temp_path / (file_path.stem + ".txt")
            if converted_txt.exists() and converted_txt.stat().st_size > 0:
                raw_text = converted_txt.read_text(encoding="utf-8", errors="replace").strip()
                raw_lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

                paragraphs = [
                    ExtractedParagraph(page_number=1, paragraph_number=i, text=line)
                    for i, line in enumerate(raw_lines, start=1)
                ]
                pages = [
                    ExtractedPage(page_number=1, text=raw_text, is_scanned=False, paragraphs=paragraphs)
                ]
                doc.title = raw_lines[0][:100] if raw_lines else file_path.stem
                doc.page_count = 1
                doc.pages = pages
                doc.paragraphs = paragraphs
                doc.extraction_status = ExtractionStatus.INDEXED.value
                return

            # If both failed, report error
            err_output = proc.stderr.decode("utf-8", errors="replace").strip() or proc.stdout.decode("utf-8", errors="replace").strip()
            doc.extraction_status = ExtractionStatus.ERROR.value
            doc.error_message = f"LibreOffice conversion failed (exit code {proc.returncode}): {err_output or 'Unknown conversion error'}"
            logger.error(f"Failed to convert {file_path}: {doc.error_message}")
