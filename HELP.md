# Medical Literature Search — Setup & User Guide

Welcome to the **Medical Literature Search System**. This guide provides step-by-step instructions to set up, run, and use the Desktop Document Indexer on both **Windows** and **Linux**.

---

## Table of Contents
1. [Overview](#1-overview)
2. [Quick Start: Windows](#2-quick-start-windows)
   - [Prerequisites](#windows-prerequisites)
   - [Method A: 1-Click Launcher (Recommended)](#method-a-1-click-launcher-windows)
   - [Method B: Manual Setup (PowerShell / Command Prompt)](#method-b-manual-setup-windows)
3. [Quick Start: Linux](#3-quick-start-linux)
   - [Prerequisites & System Packages](#linux-prerequisites)
   - [Method A: 1-Click Launcher](#method-a-1-click-launcher-linux)
   - [Method B: Headless / SSH CLI Usage](#method-b-headless--ssh-cli-usage)
   - [Running the GUI on Headless / Cloud Servers (Xvfb)](#running-gui-on-headless-servers-xvfb)
4. [Using the Graphical Interface (GUI)](#4-using-the-graphical-interface-gui)
   - [Indexing Documents](#indexing-documents)
   - [Full-Text Search & Filters](#full-text-search--filters)
   - [Cardiology Synonyms Management](#cardiology-synonyms-management)
   - [Exporting for Mobile PWA](#exporting-for-mobile-pwa)
5. [Command-Line Interface (CLI) Reference](#5-command-line-interface-cli-reference)
6. [Troubleshooting & FAQ](#6-troubleshooting--faq)

---

## 1. Overview

The **Medical Literature Search System** indexes large collections of medical documents (DOCX, PDF, legacy DOC, and TXT) into a compact SQLite full-text search database (`FTS5`).

- **Supported Document Formats**:
  - `.docx` — Modern Microsoft Word documents (text, headings, tables, headers/footers).
  - `.pdf` — Native PDFs (digital text) + Scanned image PDFs (automatic OCR via Tesseract).
  - `.doc` — Legacy Word 97–2003 documents (converted via LibreOffice headless).
  - `.txt` — Plain text files (UTF-8, UTF-16, Latin-1).
- **Key Features**:
  - Instant sub-millisecond full-text search with BM25 ranking and `<mark>` snippet highlights.
  - Built-in cardiology acronym/synonym expansion (e.g., `LM` ↔ `Left Main`, `CTO` ↔ `Chronic Total Occlusion`).
  - Incremental scanning: only processes new or modified files.
  - High-ratio Zstandard compression (reduces a multi-gigabyte library index to tens or hundreds of megabytes).
  - One-click export for offline search in the companion Mobile PWA (iPhone, iPad, Android).

---

## 2. Quick Start: Windows

### Windows Prerequisites

1. **Python 3.12 or newer**:
   - Download from [python.org/downloads](https://www.python.org/downloads/).
   - **IMPORTANT**: During installation, check the box **"Add Python to PATH"**.
2. **Git** (optional, to clone repository):
   - Download from [git-scm.com](https://git-scm.com/).
3. **LibreOffice** (optional, only required if you have legacy `.doc` files):
   - Download free from [libreoffice.org](https://www.libreoffice.org/).
   - Install to standard path (`C:\Program Files\LibreOffice\`).
4. **Tesseract OCR** (optional, only required if you have scanned image PDFs):
   - Download Windows installer from [UB-Mannheim Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki).
   - Standard path: `C:\Program Files\Tesseract-OCR\tesseract.exe`.
   - To index Hindi medical documents, select the **Hindi language data** component during setup.

---

### Method A: 1-Click Launcher (Windows)

The repository includes a ready-to-use batch file that creates your Python environment, installs dependencies, and starts the application automatically.

1. Open your cloned folder:
   ```cmd
   cd C:\path\to\searchengine
   ```
2. Double-click **`run_indexer.bat`** (or execute in Command Prompt):
   ```cmd
   run_indexer.bat
   ```
3. On first run, it will:
   - Create a virtual environment (`venv`).
   - Install all required libraries (`PySide6`, `PyMuPDF`, `python-docx`, `zstandard`, etc.).
   - Launch the desktop GUI window.
4. On subsequent runs, it opens the app immediately.

---

### Method B: Manual Setup (Windows)

If you prefer using PowerShell or Command Prompt manually:

1. **Open PowerShell or Command Prompt** in the project directory:
   ```powershell
   cd C:\path\to\searchengine
   ```

2. **Create and activate a virtual environment**:
   ```powershell
   python -m venv venv
   venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Run the Graphical App**:
   ```powershell
   python -m indexer.main
   ```

5. **Or run the Command-Line Interface (CLI)**:
   ```powershell
   python -m indexer.cli --help
   ```

---

## 3. Quick Start: Linux

### Linux Prerequisites

Install Python, virtual environment tools, and optional converter packages using `apt` (Ubuntu/Debian) or equivalent package manager:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip

# Optional (for legacy .doc support):
sudo apt install -y libreoffice-writer

# Optional (for scanned PDF OCR support in English and Hindi):
sudo apt install -y tesseract-ocr tesseract-ocr-hin fonts-deva fonts-noto-core
```

---

### Method A: 1-Click Launcher (Linux)

A launcher script is included that handles venv creation, packages, and smart display detection:

1. Open terminal and navigate to the repository:
   ```bash
   cd /home/ubuntu/searchengine
   ```

2. Ensure launcher has execution permissions:
   ```bash
   chmod +x run_indexer.sh
   ```

3. Run the script:
   ```bash
   ./run_indexer.sh
   ```
   - **With Desktop/Display (Ubuntu Desktop, XRDP, VNC)**: Launches the PySide6 Graphical Desktop GUI.
   - **Headless SSH (No Display)**: Displays a helpful notice and launches the CLI interface automatically.

---

### Method B: Headless / SSH CLI Usage

When operating on a remote cloud server via SSH without a graphical display, you can use the CLI directly:

1. **Activate the environment**:
   ```bash
   source venv/bin/activate
   ```

2. **Check database statistics**:
   ```bash
   python -m indexer.cli stats
   ```

3. **Scan and index documents**:
   ```bash
   python -m indexer.cli scan sample_corpus/
   # Or multiple folders:
   python -m indexer.cli scan /path/to/folder1 /path/to/folder2
   ```

4. **Search through your indexed literature**:
   ```bash
   python -m indexer.cli search "cardiac resynchronization"
   python -m indexer.cli search "LM stenosis" --synonyms
   ```

5. **Export a mobile-ready database**:
   ```bash
   python -m indexer.cli export --type search-only --zstd --out ./exports
   ```

---

### Running GUI on Headless Servers (Xvfb)

If you are testing GUI features or running GUI tests on a headless server without a physical monitor:

```bash
# Install virtual framebuffer
sudo apt install -y xvfb

# Run the GUI inside a virtual screen (1920x1080x24)
xvfb-run -s "-screen 0 1920x1080x24" python -m indexer.main
```

---

## 4. Using the Graphical Interface (GUI)

The desktop window is divided into two main tabs: **Indexer & Dashboard** and **Search & Explore**.

```
+-----------------------------------------------------------------------------------+
|  Medical Literature Search Indexer                                       [_][#][X] |
+-----------------------------------------------------------------------------------+
|  [Tab 1: Indexer & Dashboard]  |  [Tab 2: Search & Explore]                       |
+-----------------------------------------------------------------------------------+
|  METRICS DASHBOARD                                                                |
|  [ Total Docs: 147 ]  [ Indexed: 147 ]  [ Failed: 3 ]  [ Paragraphs: 2,580 ]      |
|  [ DB Size: 7.2 MB ]  [ Index Size: 5.1 MB ]  [ Total Pages: 420 ]                |
+-----------------------------------------------------------------------------------+
|  DOCUMENT FOLDERS TO INDEX:                                                       |
|  + [ /home/ubuntu/searchengine/sample_corpus ]                                    |
|  [+ Add Folder]   [- Remove Folder]                                               |
+-----------------------------------------------------------------------------------+
|  CONTROLS:                                                                        |
|  [ Start Indexing ]  [ Pause ]  [ Resume ]  [ Cancel ]  [ Retry Failed ]          |
|  Progress: [==================================] 100% (147/147)                   |
+-----------------------------------------------------------------------------------+
|  ACTION BUTTONS:                                                                  |
|  [ Export for Mobile PWA... ]  [ Manage Synonyms... ]  [ Clear Database ]         |
+-----------------------------------------------------------------------------------+
```

### Indexing Documents
1. Click **Add Folder** to select one or more directories containing your medical files.
2. Click **Start Indexing**.
3. The real-time progress bar will show current file processing, elapsed time, and live logs.
4. If needed, click **Pause** to temporarily suspend processing without losing progress, or **Cancel** to cleanly stop.
5. If corrupted documents fail, click **Retry Failed** to re-attempt extraction.

### Full-Text Search & Filters
1. Switch to **Tab 2: Search & Explore**.
2. Type in your search term. Auto-complete suggestions appear instantly as you type.
3. Supported query patterns:
   - **Phrases**: `"bioresorbable vascular scaffold"`
   - **Boolean logic**: `stent AND restenosis`, `aspirin OR clopidogrel`
   - **Negation**: `pacemaker -infection` (finds pacemakers excluding infection)
   - **Prefix wildcards**: `litho*` (matches lithotripsy, lithotripsy-assisted, etc.)
4. **Cardiology Synonym Expansion**:
   - Check the **"Expand Cardiology Synonyms"** box.
   - Searching for `LM` automatically searches for `(LM OR "left main")`.
   - Searching for `CTO` automatically searches for `(CTO OR "chronic total occlusion")`.
5. **Filters**: Filter results by format (`PDF`, `DOCX`, `DOC`, `TXT`) or date range.
6. Click any result to view full paragraph context, page number, and document metadata.

### Cardiology Synonyms Management
1. Click **Manage Synonyms...** in Tab 1 or from the Search Tab.
2. View the built-in dictionary of cardiology abbreviations (e.g., `ELCA`, `IVUS`, `OCT`, `IVL`, `ISR`, `TAVI`, `CABG`, `FFR`, etc.).
3. Add custom terms or abbreviations anytime:
   - Enter **Term**: `TAVR`
   - Enter **Synonyms (comma-separated)**: `transcatheter aortic valve replacement, TAVI`
   - Click **Save**.

### Exporting for Mobile PWA
1. Click **Export for Mobile PWA...** on Tab 1.
2. Choose your export format:
   - **Search-Only Compact Database (`.db` or `.db.zst`)** *(Recommended)*:
     - Strips error logs, deduplicates b-trees, optimizes FTS5 index segments, and runs vacuum.
     - Compresses by over **95%** with Zstandard (a 7.2 MB database compresses to ~200 KB).
     - Generates an official `SHA-256` checksum file for tamper-proof transfers.
   - **Full Database Backup**: Complete snapshot of all document metadata and extraction logs.
   - **Incremental Delta Package (`.json` or `.json.zst`)**: Contains only documents changed or added since a baseline date.
3. Click **Start Export**. The output file is ready to be uploaded to Google Drive or loaded into the mobile PWA.

---

## 5. Command-Line Interface (CLI) Reference

The CLI provides complete control without opening the GUI.

### 1. Show Statistics
```bash
python -m indexer.cli stats
```
Displays total documents, indexed count, failed count, total pages, paragraphs, database size, and last indexed timestamp.

### 2. Scan and Index Folders
```bash
# Index a single folder
python -m indexer.cli scan /path/to/medical_docs

# Index multiple folders
python -m indexer.cli scan /path/to/guidelines /path/to/case_reports
```

### 3. Search the Database
```bash
# Standard keyword search
python -m indexer.cli search "coronary artery disease"

# Phrase search with limit
python -m indexer.cli search "\"drug eluting stent\"" --limit 5

# Search with cardiology synonym expansion enabled
python -m indexer.cli search "LM bifurcation" --synonyms

# Search with format filter (e.g. PDF only)
python -m indexer.cli search "angioplasty" --format pdf
```

### 4. Get Search Suggestions (Autocomplete)
```bash
python -m indexer.cli suggest "stent"
python -m indexer.cli suggest "angio" --limit 10
```

### 5. Manage Synonyms
```bash
# List all active cardiology synonyms
python -m indexer.cli synonyms --list

# Add a new medical synonym
python -m indexer.cli synonyms --add "STEMI" --expanded "ST elevation myocardial infarction"
```

### 6. Export Database
```bash
# Export compressed search-only database for Mobile PWA
python -m indexer.cli export --type search-only --zstd --out ./exports

# Export full database
python -m indexer.cli export --type full --out ./backups

# Export incremental delta package (since date)
python -m indexer.cli export --type delta --since 2026-01-01 --zstd --out ./exports
```

### 7. Retry Failed Documents
```bash
python -m indexer.cli retry
```

### 8. Clear / Reset Database
```bash
python -m indexer.cli clear --force
```

---

## 6. Troubleshooting & FAQ

### Q1: `python` or `python3` command is not recognized (Windows)
- **Cause**: Python was installed without checking "Add Python to PATH".
- **Fix**: Re-run the Python installer, choose **Modify**, and check **"Add Python to environment variables / PATH"**. Alternatively, locate where Python was installed (e.g., `C:\Users\<Name>\AppData\Local\Programs\Python\Python312`) and add it to System Environment Variables.

### Q2: `.doc` (Word 97–2003) files are skipped or show warning
- **Cause**: LibreOffice is not installed or not in the default directory.
- **Fix**:
  - On Windows: Install LibreOffice to `C:\Program Files\LibreOffice\program\soffice.exe`.
  - On Linux: Run `sudo apt install -y libreoffice-writer`.
  - Note: Modern `.docx` files do **not** need LibreOffice and are extracted directly by Python.

### Q3: Scanned PDFs show 0 text or "Scanned page image requires OCR"
- **Cause**: Tesseract OCR engine is not installed.
- **Fix**:
  - On Windows: Install Tesseract to `C:\Program Files\Tesseract-OCR\tesseract.exe`.
  - On Linux: Run `sudo apt install -y tesseract-ocr tesseract-ocr-hin`.

### Q4: GUI fails to start on Linux cloud server (`cannot connect to X server`)
- **Cause**: Linux remote session has no active display (`$DISPLAY` is unset).
- **Fix**:
  - Use the CLI directly: `python -m indexer.cli stats` or `./run_indexer.sh` (which auto-detects headless mode).
  - Or use virtual display: `xvfb-run python -m indexer.main`.
  - Or connect using a remote desktop environment like XRDP / VNC.

### Q5: How do I transfer the search index to iPhone / iPad / Android?
- Export the database using **Search-Only + Zstandard** (`.db.zst` or `.db`).
- Upload the file to your Google Drive or web server.
- In the **Medical Literature Search PWA**, click **"Import Database"** and select the exported file.
- The PWA saves it directly in high-performance browser storage (OPFS) for instant offline search on mobile.

---

## Need Help?
For issues, bug reports, or feature requests, visit the project repository:
[https://github.com/gunjanj20000/reportsearch-](https://github.com/gunjanj20000/reportsearch-)
