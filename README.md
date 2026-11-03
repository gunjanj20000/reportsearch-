# Medical Literature Search — Windows Indexer & Universal Search Engine

A high-performance document indexing and universal search system designed for large medical literature libraries (16 GB+, DOC, DOCX, PDF, and TXT).

The project consists of two core components:
1. **Windows Indexer Application**: Desktop application (PySide6 + SQLite FTS5) that recursively indexes medical literature, extracts rich text, tables, and metadata, runs OCR on scanned documents, and compiles a compact SQLite FTS5 search database.
2. **Universal Offline Search PWA**: Responsive React + TypeScript + SQLite WASM Progressive Web App enabling instant full-text search across mobile devices (iOS / Android) and desktop without carrying the original files.

---

## Phase 1 Implementation Summary

Phase 1 delivers the complete document indexing system and desktop application:

- **PySide6 Desktop Application & CLI**:
  - Full-featured GUI with interactive dashboard, multi-folder selection, progress tracking, live activity log, and controls.
  - Headless CLI interface (`indexer.main scan`, `stats`, `retry`, `clear`) for server environments, automated pipelines, and headless testing.
- **8-Metric Live Dashboard**:
  1. Total Indexed Documents
  2. Total Original File Size
  3. Extracted Text Size
  4. Search Database Size
  5. Number of PDF Pages
  6. Number of Word Documents (.docx / .doc)
  7. Number of Scanned PDFs (with OCR)
  8. Last Indexing Date
- **Document Extractors**:
  - **DOCX**: Extracts paragraphs, headings, complex tables (preserving row-by-row structure), headers, footers, and metadata via `python-docx`.
  - **DOC**: Converts legacy Word 97-2003 `.doc` files via LibreOffice headless, falling back to rich text extraction without silent skips.
  - **PDF**: Extracts text page-by-page via `PyMuPDF`, preserves paragraph boundaries, detects scanned/image-only pages, and triggers Tesseract OCR (`eng+hin`) for scanned and mixed documents.
  - **TXT**: Plain-text extractor with encoding autodetection (`utf-8`, `utf-16`, `latin-1`).
- **SQLite FTS5 Architecture**:
  - Relational tables: `documents`, `document_pages`, `document_paragraphs`, `collections`, `document_collections`.
  - Full-text search virtual table: `search_index` using FTS5 with `unicode61 remove_diacritics 2` tokenizer.
  - Supports phrase search, Boolean `AND` / `OR` / `NOT`, prefix search, ranking, and snippet highlighting.
- **Intelligent Incremental Synchronization**:
  - Automatically identifies new, modified, unchanged, and deleted documents using mtime, file size, and chunked SHA-256 streaming.
  - Skips unchanged files (instant zero-work re-scans).
- **Control Features**:
  - Pause, Resume, Cancel, and Retry Failed Documents.
- **Realistic Medical Test Corpus**:
  - 150 test documents covering cardiology interventions (Left Main, CTO, IVUS, OCT, ELCA, IVL, ISR, TAVI), tables, multi-page PDFs, legacy `.doc` files, scanned cath lab reports, mixed PDFs, Hindi literature, duplicate files, and corrupted files.

---

## Directory Structure

```
searchengine/
├── indexer/
│   ├── __init__.py
│   ├── config.py                 # Configuration, paths, tool discovery (LibreOffice, Tesseract)
│   ├── models.py                 # Dataclasses (ExtractedDocument, DashboardStats, ExtractionStatus)
│   ├── cli.py                    # Command-line interface
│   ├── main.py                   # Application entrypoint (GUI / CLI)
│   ├── database/
│   │   ├── __init__.py
│   │   ├── schema.py             # SQLite and FTS5 DDL schema
│   │   └── connection.py         # Thread-safe DatabaseManager, transactions, queries, dashboard stats
│   ├── extractors/
│   │   ├── __init__.py
│   │   ├── base.py               # Abstract BaseExtractor and SHA-256 streaming
│   │   ├── docx_extractor.py     # DOCX extractor (paragraphs, tables, headers/footers)
│   │   ├── doc_extractor.py      # Legacy DOC extractor (LibreOffice headless)
│   │   ├── pdf_extractor.py      # PDF extractor with scanned detection and Tesseract OCR (eng+hin)
│   │   ├── txt_extractor.py      # Plain-text multi-encoding extractor
│   │   └── factory.py            # ExtractorFactory and dispatcher
│   ├── scanner/
│   │   ├── __init__.py
│   │   └── scanner.py            # Recursive multi-folder scanner & change detection
│   ├── engine/
│   │   ├── __init__.py
│   │   └── indexer_engine.py     # Orchestrator with pause/resume/cancel/retry
│   └── ui/
│       ├── __init__.py
│       ├── dashboard_widget.py   # 8-metric modern dashboard widget
│       ├── worker.py             # PySide6 QThread background worker
│       └── main_window.py        # Complete desktop MainWindow interface
├── tests/
│   ├── __init__.py
│   ├── test_extractors.py        # Tests for DOCX, DOC, PDF, Scanned OCR, Hindi, TXT, Corrupted
│   ├── test_database.py          # Tests for SQLite schema, cascades, and FTS5 search
│   ├── test_scanner.py           # Tests for file scanning, hashing, and incremental detection
│   ├── test_engine.py            # Tests for indexing pipeline, pause/resume/cancel/retry
│   └── test_gui.py               # Offscreen PySide6 GUI tests
├── sample_corpus/                # Generated 150-document test dataset
├── generate_sample_corpus.py     # Script to generate realistic test dataset
├── requirements.txt              # Python dependencies
└── README.md                     # Documentation
```

---

## Installation & Setup

### 1. System Dependencies

- **Python 3.12+**
- **LibreOffice** (for legacy `.doc` conversion):
  - Linux: `sudo apt-get install -y libreoffice-writer`
  - Windows: Install LibreOffice to default directory (`C:\Program Files\LibreOffice`)
- **Tesseract OCR** (for scanned document text extraction):
  - Linux: `sudo apt-get install -y tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin`
  - Windows: Install Tesseract-OCR to default directory (`C:\Program Files\Tesseract-OCR`)

### 2. Python Virtual Environment

```bash
cd /home/ubuntu/searchengine
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Usage

### Launch GUI Application (Desktop)

```bash
python -m indexer.main
```
*(On headless Linux, launch with `QT_QPA_PLATFORM=offscreen` or X11/VNC).*

### Launch Command-Line Interface (CLI)

1. **View Dashboard Statistics**:
   ```bash
   python -m indexer.main stats
   ```

2. **Scan & Index Medical Folders**:
   ```bash
   python -m indexer.main scan /path/to/folder1 /path/to/folder2
   ```

3. **Retry Failed Documents**:
   ```bash
   python -m indexer.main retry
   ```

4. **Reset Database**:
   ```bash
   python -m indexer.main clear
   ```

---

## Running the Automated Test Suite

Run the full pytest suite (21 unit and integration tests):

```bash
QT_QPA_PLATFORM=offscreen pytest -v tests/
```

All 21 tests validate:
- Extraction accuracy across DOCX (tables, titles, headers), DOC (LibreOffice conversion), PDF, scanned PDF OCR, mixed PDFs, Hindi literature, and plain text.
- Graceful error handling on damaged/corrupted files.
- SQLite schema, cascading deletes, and FTS5 search index queries.
- Recursive scanner and incremental change detection.
- Indexing engine lifecycle (pause, resume, cancel, retry).
- Offscreen PySide6 GUI and dashboard widget updates.

---

## Sample Corpus Verification Results

Indexing the sample corpus of 150 realistic medical documents produced the following dashboard metrics:

```
============================================================
      MEDICAL LITERATURE SEARCH — INDEXER DASHBOARD
============================================================
  1. Total Indexed Documents:   147
  2. Total Original File Size:  210.80 MB
  3. Extracted Text Size:       281.2 KB
  4. Search Database Size:      7.28 MB
  5. Number of PDF Pages:       200
  6. Number of Word Documents:  66
  7. Number of Scanned PDFs:    25
  8. Last Indexing Date:        2026-11-03 01:07:24
============================================================
  LibreOffice:   Found (/usr/bin/libreoffice)
  Tesseract OCR: Found (/usr/bin/tesseract)
  Database Path: /home/ubuntu/searchengine/data/medical_search.db
============================================================
```

Subsequent scan completed in `< 0.2s` with:
`150 found, 0 to index (0 new, 0 modified), 150 unchanged, 0 deleted.`
