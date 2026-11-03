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

---

## Phase 2: SQLite FTS5 Database & Search Engine

Phase 2 implements the complete, high-performance search engine architecture:

### 1. Advanced FTS5 Query Parsing & Sanitization (`indexer/search/query_parser.py`)
- **Exact Phrase Search**: `"left main"` matches precise word sequences.
- **Implicit AND**: Multi-word queries (`ivus cto`) automatically construct conjunction queries without syntax errors.
- **Explicit Boolean Operators**: Standard `AND`, `OR`, `NOT` support.
- **Exclusion Terms**: Hyphenated terms (`stent -thrombosis`) safely translated to `stent NOT thrombosis`.
- **Prefix Wildcards**: `litho*`, `athero*` for stem matching.
- **Syntax Robustness**: Automatically balances unclosed quotes, sanitizes punctuation, and prevents SQLite runtime syntax errors.

### 2. BM25 Ranking & Snippet Generation (`indexer/search/search_service.py`)
- Multi-column BM25 relevance scoring:
  - Document Title weight: `5.0`
  - Matching Paragraph weight: `2.0`
  - Page Text weight: `1.0`
- Dynamic snippet extraction with high-contrast highlighting (`<mark>...</mark>`).
- Granular mapping back to exact source document, page number, and paragraph index.
- Search filters: Format (`.pdf`, `.docx`, `.doc`, `.txt`), Collections, Date ranges.

### 3. Cardiology Synonym Dictionary & Query Expansion (`indexer/search/synonyms.py`)
- Database-backed `synonyms` table seeded with 25 primary interventional cardiology terms:
  - `LM` ↔ `Left Main`
  - `CTO` ↔ `Chronic Total Occlusion`
  - `ELCA` ↔ `Excimer Laser Coronary Atherectomy`
  - `IVUS` ↔ `Intravascular Ultrasound`
  - `OCT` ↔ `Optical Coherence Tomography`
  - `IVL` ↔ `Intravascular Lithotripsy`
  - `ISR` ↔ `In-Stent Restenosis`
  - `TAVI` / `TAVR` ↔ `Transcatheter Aortic Valve Implantation / Replacement`
  - `CABG`, `PCI`, `FFR`, `iFR`, `DES`, `BMS`, `DCB`, `MLA`, `MSA`, `EEL`, `LAD`, `LCx`, `RCA`, etc.
- **Transparent Expansion Mode**: Never silently overwrites user queries. When enabled, expands e.g. `LM` to `("LM" OR "Left Main")`, and surfaces the expansion transparently in results.
- **User Extensible**: Full CRUD dialog (`SynonymsDialog`) in the GUI and CLI (`indexer.main synonyms --add`).

### 4. Search Suggestions & Auto-Complete (`indexer/search/suggestions.py`)
- Sub-millisecond typeahead powered by SQLite `fts5vocab` virtual table and document title indexing.
- Contextual suggestions across terms, document titles, and cardiology acronyms.

### 5. Performance Benchmarks (`benchmark_search.py`)
Tested across 19 query variations on the 150-document indexed corpus:
- **Average Search Latency**: `6.41 ms`
- **Max Observed Latency**: `14.52 ms`
- **Sub-15ms performance** achieved for complex Boolean, phrase, and multi-term synonym expansions.

---

## Phase 3: Portable Database Export & Zstandard Compression

Phase 3 delivers a portable database export system that compiles the search index into compact, self-contained packages for offline mobile PWA synchronization:

### 1. Export Package Variants (`indexer/export/exporter.py`)
1. **Search-Only Compact Database (`.db` / `.db.zst`)**:
   - Excludes failed/corrupted files and internal processing logs.
   - Preserves complete document metadata, original paths, Google Drive URLs, page numbers, paragraph text, collections, and synonyms.
   - Optimizes FTS5 virtual tables by merging all b-tree segments into a single compact index (`INSERT INTO search_index(search_index) VALUES('optimize');`).
   - Runs `VACUUM` to eliminate all unallocated pages.
   - Result: 7.2 MB uncompressed database shrinks to **~206 KB** with Zstandard compression (>97% reduction).
2. **Full Database Backup (`.db` / `.db.zst`)**:
   - Creates a consistent snapshot using SQLite `VACUUM INTO` without interrupting active read/write operations.
3. **Incremental Update Package (`.json` / `.json.zst`)** (`indexer/export/delta_package.py`):
   - Exports delta records modified since a baseline date/timestamp.
   - Enables mobile clients to synchronize updates in packages as small as **~37 KB**.

### 2. High-Efficiency Zstandard (`zstd`) Streaming
- Integrated streaming compression with configurable levels (1–19, default 10).
- Automatic SHA-256 integrity checksum generation for tamper-proof mobile imports.
- Pre-export size preview calculating actual database bytes and document counts.

### 3. User Interfaces & Tooling
- **Desktop UI**: `ExportDialog` in PySide6 with package choice, live size preview, zstd toggle, and export summary.
- **CLI Command**:
  ```bash
  python -m indexer.main export --type search-only --compress -o medical_search_compact.db.zst
  ```
