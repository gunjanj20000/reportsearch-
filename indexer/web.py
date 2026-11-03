"""
Self-contained, zero-dependency Web GUI and REST API for Medical Literature Search.
Provides complete indexing, live stats, search with cardiology synonyms, and mobile database export.
Works in any browser without requiring PySide6/Qt or GUI libraries.
"""

from __future__ import annotations
import json
import os
import sys
import threading
import time
import urllib.parse
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import logger, DEFAULT_DB_PATH, EXPORTS_DIR, find_libreoffice_binary, find_tesseract_binary, format_bytes
from .database.connection import DatabaseManager
from .engine.indexer_engine import IndexerEngine
from .search.search_service import SearchService, SearchResponse
from .search.suggestions import SuggestionService
from .search.synonyms import SynonymManager
from .export.exporter import ExportManager


# Global state for web server background tasks
class WebState:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path
        self.db = DatabaseManager(db_path)
        self.engine = IndexerEngine(db_manager=self.db)
        self.export_manager = ExportManager(self.db)

        # Lazy / per-thread or connection-backed search services
        self.conn = self.db.get_connection()
        self.search_service = SearchService(self.conn)
        self.suggestions_service = SuggestionService(self.conn)
        self.synonym_manager = SynonymManager(self.conn)

        # Progress tracking
        self.progress_lock = threading.Lock()
        self.progress_current = 0
        self.progress_total = 0
        self.progress_filename = ""
        self.progress_message = "Ready"
        self.activity_logs: List[str] = []
        self.is_indexing = False

        # Attach callbacks
        self.engine.on_progress = self._on_progress
        self.engine.on_error = self._on_error
        self.engine.on_status_changed = self._on_status_changed

    def _on_progress(self, cur: int, tot: int, filename: str, msg: str) -> None:
        with self.progress_lock:
            self.progress_current = cur
            self.progress_total = tot
            self.progress_filename = filename
            self.progress_message = msg
            if filename:
                self.activity_logs.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
                if len(self.activity_logs) > 100:
                    self.activity_logs.pop(0)

    def _on_error(self, path: str, err: str) -> None:
        with self.progress_lock:
            self.activity_logs.append(f"[{time.strftime('%H:%M:%S')}] ERROR: {Path(path).name} - {err}")
            if len(self.activity_logs) > 100:
                self.activity_logs.pop(0)

    def _on_status_changed(self, status: str) -> None:
        with self.progress_lock:
            self.activity_logs.append(f"[{time.strftime('%H:%M:%S')}] Status: {status}")

    def get_progress_data(self) -> Dict[str, Any]:
        with self.progress_lock:
            return {
                "is_indexing": self.is_indexing,
                "status": self.engine.status,
                "current": self.progress_current,
                "total": self.progress_total,
                "filename": self.progress_filename,
                "message": self.progress_message,
                "logs": self.activity_logs[-30:]
            }


# Singleton web state
_state: Optional[WebState] = None


class MedicalSearchHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler providing REST endpoints and serving the modern SPA."""

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress noisy standard HTTP logs, keep custom logger
        pass

    def send_json(self, data: Any, status: int = 200) -> None:
        payload = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        params = urllib.parse.parse_qs(parsed_url.query)

        # 1. Dashboard Stats API
        if path == "/api/stats":
            stats = _state.db.get_dashboard_stats()
            lo = find_libreoffice_binary()
            tess = find_tesseract_binary()
            self.send_json({
                "total_documents": stats.total_documents,
                "total_original_file_size": stats.total_original_file_size,
                "total_original_file_size_fmt": format_bytes(stats.total_original_file_size),
                "extracted_text_size": stats.extracted_text_size,
                "extracted_text_size_fmt": format_bytes(stats.extracted_text_size),
                "database_size": stats.database_size,
                "database_size_fmt": format_bytes(stats.database_size),
                "number_of_pdf_pages": stats.number_of_pdf_pages,
                "number_of_word_documents": stats.number_of_word_documents,
                "number_of_scanned_pdfs": stats.number_of_scanned_pdfs,
                "last_indexing_date": stats.last_indexing_date,
                "libreoffice_found": bool(lo),
                "libreoffice_path": lo or "",
                "tesseract_found": bool(tess),
                "tesseract_path": tess or ""
            })
            return

        # 2. Indexing Progress API
        if path == "/api/scan/progress":
            self.send_json(_state.get_progress_data())
            return

        # 3. Search API
        if path == "/api/search":
            q = params.get("q", [""])[0].strip()
            expand_syn = params.get("synonyms", ["false"])[0].lower() in ("true", "1", "yes")
            fmt = params.get("format", [""])[0].strip().lower()
            try:
                page = int(params.get("page", ["1"])[0])
                limit = int(params.get("limit", ["20"])[0])
            except ValueError:
                page, limit = 1, 20

            if not q:
                self.send_json({"results": [], "total_count": 0, "execution_time_ms": 0.0, "parsed_query": ""})
                return

            extensions = [f".{fmt}"] if fmt and fmt != "all" else None
            res = _state.search_service.search(
                query=q,
                page=page,
                page_size=limit,
                expand_synonyms=expand_syn,
                extensions=extensions
            )
            self.send_json({
                "query": res.query,
                "parsed_query": res.parsed_fts_query,
                "expanded_query": res.expanded_query,
                "synonyms_applied": res.synonyms_applied,
                "total_count": res.total_count,
                "execution_time_ms": res.execution_time_ms,
                "results": [
                    {
                        "document_id": r.document_id,
                        "filename": r.filename,
                        "file_type": r.extension.replace(".", "").upper(),
                        "title": r.title,
                        "page_number": r.page_number,
                        "paragraph_number": r.paragraph_number,
                        "snippet_html": r.snippet,
                        "rank_score": r.rank_score,
                        "source_path": r.source_path,
                        "file_size": r.file_size
                    }
                    for r in res.items
                ]
            })
            return

        # 4. Suggestions / Autocomplete API
        if path == "/api/suggest":
            q = params.get("q", [""])[0].strip()
            limit = int(params.get("limit", ["8"])[0]) if "limit" in params else 8
            suggs = _state.suggestions_service.get_suggestions(q, limit=limit)
            self.send_json({"prefix": q, "suggestions": suggs})
            return

        # 5. Synonyms List API
        if path == "/api/synonyms":
            all_syns = _state.synonym_manager.get_all()
            self.send_json({"synonyms": all_syns})
            return

        # 6. Database Export Size Preview API
        if path == "/api/export/preview":
            prev = _state.export_manager.get_database_size_preview()
            actual_sz = prev["actual_db_size"]
            est_search_sz = int(actual_sz * 0.75)
            est_zstd_sz = int(est_search_sz * 0.05)
            self.send_json({
                "actual_db_size": actual_sz,
                "actual_db_size_fmt": format_bytes(actual_sz),
                "estimated_search_db_size": est_search_sz,
                "estimated_search_db_size_fmt": format_bytes(est_search_sz),
                "estimated_zstd_size": est_zstd_sz,
                "estimated_zstd_size_fmt": format_bytes(est_zstd_sz),
                "total_documents": prev["total_documents"],
                "total_paragraphs": prev["total_paragraphs"],
                "extracted_text_size": prev["extracted_text_size"],
                "extracted_text_size_fmt": format_bytes(prev["extracted_text_size"]),
                "last_indexed": prev.get("last_indexed")
            })
            return

        # 7. File Download API
        if path.startswith("/api/download/"):
            filename = os.path.basename(path[len("/api/download/"):])
            filepath = EXPORTS_DIR / filename
            if filepath.exists() and filepath.is_file():
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("Content-Length", str(filepath.stat().st_size))
                self.end_headers()
                with open(filepath, "rb") as f:
                    while chunk := f.read(65536):
                        self.wfile.write(chunk)
                return
            else:
                self.send_error(404, "Export file not found.")
                return

        # 8. Serve Embedded Modern Web App HTML
        if path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            html_bytes = SPA_HTML.encode("utf-8")
            self.send_header("Content-Length", str(len(html_bytes)))
            self.end_headers()
            self.wfile.write(html_bytes)
            return

        self.send_error(404, "Not Found")

    def do_POST(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        # Read JSON body
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {}

        # 1. Trigger Indexing
        if path == "/api/scan":
            if _state.is_indexing:
                self.send_json({"error": "Indexing is already in progress."}, status=400)
                return

            folders = data.get("folders", [])
            if not folders:
                # Default to sample_corpus if available
                sample_path = Path(__file__).resolve().parent.parent / "sample_corpus"
                if sample_path.exists():
                    folders = [str(sample_path)]
                else:
                    self.send_json({"error": "No folders specified and sample_corpus not found."}, status=400)
                    return

            def run_scan_worker():
                _state.is_indexing = True
                try:
                    folder_paths = [Path(f) for f in folders]
                    _state.engine.index_folders(folder_paths)
                except Exception as e:
                    logger.error(f"Error in web indexing scan: {e}")
                finally:
                    _state.is_indexing = False

            thread = threading.Thread(target=run_scan_worker, daemon=True)
            thread.start()
            self.send_json({"success": True, "message": "Indexing started."})
            return

        # 2. Control Indexing (Pause / Resume / Cancel)
        if path == "/api/scan/control":
            action = data.get("action", "").lower()
            if action == "pause":
                _state.engine.pause()
                self.send_json({"success": True, "status": _state.engine.status})
            elif action == "resume":
                _state.engine.resume()
                self.send_json({"success": True, "status": _state.engine.status})
            elif action == "cancel":
                _state.engine.cancel()
                self.send_json({"success": True, "status": _state.engine.status})
            else:
                self.send_json({"error": f"Unknown action: {action}"}, status=400)
            return

        # 3. Retry Failed
        if path == "/api/retry":
            if _state.is_indexing:
                self.send_json({"error": "Indexing is currently running."}, status=400)
                return

            def run_retry_worker():
                _state.is_indexing = True
                try:
                    _state.engine.retry_failed()
                except Exception as e:
                    logger.error(f"Error in retry worker: {e}")
                finally:
                    _state.is_indexing = False

            thread = threading.Thread(target=run_retry_worker, daemon=True)
            thread.start()
            self.send_json({"success": True, "message": "Retrying failed documents started."})
            return

        # 4. Add / Update Synonym
        if path == "/api/synonyms":
            term = data.get("term", "").strip()
            expanded = data.get("expanded", "").strip()
            if not term or not expanded:
                self.send_json({"error": "Both 'term' and 'expanded' are required."}, status=400)
                return

            _state.synonym_manager.add(term, expanded)
            self.send_json({"success": True, "message": f"Synonym added for '{term}'."})
            return

        # 5. Export Portable Database for Mobile PWA
        if path == "/api/export":
            export_type = data.get("type", "search-only")
            compress = data.get("compress", True)
            since = data.get("since", "2000-01-01")

            EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")

            try:
                if export_type == "search-only":
                    ext = ".db.zst" if compress else ".db"
                    target_file = EXPORTS_DIR / f"medical_search_portable_{timestamp}{ext}"
                    res = _state.export_manager.export_search_only_database(target_file, compress=compress)
                elif export_type == "full":
                    ext = ".db.zst" if compress else ".db"
                    target_file = EXPORTS_DIR / f"medical_search_backup_{timestamp}{ext}"
                    res = _state.export_manager.export_full_database(target_file, compress=compress)
                else:
                    ext = ".json.zst" if compress else ".json"
                    target_file = EXPORTS_DIR / f"medical_search_delta_{timestamp}{ext}"
                    res = _state.export_manager.export_incremental_package(target_file, since_date=since, compress=compress)

                self.send_json({
                    "success": True,
                    "filename": res.output_path.name,
                    "download_url": f"/api/download/{res.output_path.name}",
                    "file_size": res.compressed_size or res.uncompressed_size,
                    "file_size_fmt": format_bytes(res.compressed_size or res.uncompressed_size),
                    "uncompressed_size_fmt": format_bytes(res.uncompressed_size),
                    "compression_ratio": res.compression_ratio_str,
                    "sha256": res.sha256_checksum,
                    "total_documents": res.total_documents,
                    "total_paragraphs": res.total_paragraphs
                })
            except Exception as e:
                logger.error(f"Export error: {e}")
                self.send_json({"error": str(e)}, status=500)
            return

        self.send_error(404, "Not Found")


SPA_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Medical Literature Search — Web Dashboard</title>
  <style>
    :root {
      --primary: #0284c7;
      --primary-dark: #0369a1;
      --bg: #f8fafc;
      --card-bg: #ffffff;
      --text: #0f172a;
      --text-muted: #64748b;
      --border: #e2e8f0;
      --accent-green: #10b981;
      --accent-amber: #f59e0b;
      --accent-red: #ef4444;
      --shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
    body { background-color: var(--bg); color: var(--text); line-height: 1.5; }
    header { background: #0f172a; color: white; padding: 1rem 1.5rem; display: flex; align-items: center; justify-content: space-between; border-bottom: 3px solid var(--primary); }
    header h1 { font-size: 1.25rem; font-weight: 700; display: flex; align-items: center; gap: 0.5rem; }
    header .status-badge { font-size: 0.8rem; background: #1e293b; padding: 0.25rem 0.6rem; border-radius: 9999px; border: 1px solid #334155; }
    .container { max-width: 1200px; margin: 1.5rem auto; padding: 0 1rem; }
    
    /* Navigation Tabs */
    .tabs { display: flex; gap: 0.5rem; border-bottom: 2px solid var(--border); margin-bottom: 1.5rem; }
    .tab-btn { background: none; border: none; padding: 0.6rem 1.2rem; font-size: 0.95rem; font-weight: 600; color: var(--text-muted); cursor: pointer; border-bottom: 3px solid transparent; margin-bottom: -2px; }
    .tab-btn.active { color: var(--primary); border-bottom-color: var(--primary); }
    .tab-content { display: none; }
    .tab-content.active { display: block; }

    /* Dashboard Metrics Cards */
    .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
    .metric-card { background: var(--card-bg); border-radius: 8px; padding: 1.2rem; border: 1px solid var(--border); box-shadow: var(--shadow); }
    .metric-title { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); font-weight: 600; margin-bottom: 0.35rem; }
    .metric-val { font-size: 1.6rem; font-weight: 700; color: var(--text); }
    .metric-sub { font-size: 0.8rem; color: var(--text-muted); margin-top: 0.2rem; }

    /* Cards & Controls */
    .card { background: var(--card-bg); border-radius: 8px; padding: 1.5rem; border: 1px solid var(--border); box-shadow: var(--shadow); margin-bottom: 1.5rem; }
    .card-title { font-size: 1.1rem; font-weight: 600; margin-bottom: 1rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }
    .form-group { margin-bottom: 1rem; }
    label { display: block; font-size: 0.85rem; font-weight: 600; color: var(--text-muted); margin-bottom: 0.3rem; }
    input[type="text"], select { width: 100%; padding: 0.6rem 0.8rem; border-radius: 6px; border: 1px solid var(--border); font-size: 0.95rem; outline: none; }
    input[type="text"]:focus { border-color: var(--primary); }
    .btn { background: var(--primary); color: white; border: none; padding: 0.6rem 1.2rem; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: 0.9rem; transition: background 0.2s; }
    .btn:hover { background: var(--primary-dark); }
    .btn-secondary { background: #64748b; }
    .btn-secondary:hover { background: #475569; }
    .btn-danger { background: var(--accent-red); }
    .btn-danger:hover { background: #dc2626; }
    .btn-group { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-top: 0.8rem; }

    /* Progress bar */
    .progress-bar-container { width: 100%; background: #e2e8f0; height: 12px; border-radius: 6px; overflow: hidden; margin: 1rem 0 0.5rem 0; }
    .progress-bar-fill { height: 100%; background: var(--primary); width: 0%; transition: width 0.3s; }
    .progress-label { font-size: 0.85rem; color: var(--text-muted); display: flex; justify-content: space-between; }

    /* Activity log */
    .log-box { background: #0f172a; color: #f1f5f9; font-family: monospace; font-size: 0.82rem; padding: 0.8rem; border-radius: 6px; height: 160px; overflow-y: auto; white-space: pre-wrap; margin-top: 1rem; }

    /* Search interface */
    .search-bar { display: flex; gap: 0.5rem; position: relative; margin-bottom: 1rem; }
    .search-options { display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; margin-bottom: 1.2rem; font-size: 0.9rem; }
    .suggestions-list { position: absolute; top: 100%; left: 0; right: 0; background: white; border: 1px solid var(--border); border-radius: 6px; box-shadow: var(--shadow); max-height: 200px; overflow-y: auto; z-index: 100; display: none; }
    .suggestion-item { padding: 0.5rem 0.8rem; cursor: pointer; font-size: 0.9rem; }
    .suggestion-item:hover { background: #e0f2fe; }

    /* Results */
    .result-card { background: white; border: 1px solid var(--border); border-radius: 8px; padding: 1.2rem; margin-bottom: 1rem; box-shadow: var(--shadow); }
    .result-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 0.4rem; }
    .result-title { font-size: 1.05rem; font-weight: 600; color: var(--primary-dark); }
    .result-badge { font-size: 0.75rem; font-weight: 600; padding: 0.2rem 0.5rem; border-radius: 4px; background: #e0f2fe; color: var(--primary-dark); text-transform: uppercase; }
    .result-meta { font-size: 0.8rem; color: var(--text-muted); margin-bottom: 0.6rem; }
    .result-snippet { font-size: 0.9rem; color: #334155; line-height: 1.6; }
    mark { background: #fef08a; padding: 0.1rem 0.2rem; border-radius: 2px; font-weight: 600; }

    /* Synonyms Table */
    table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
    th, td { padding: 0.6rem 0.8rem; text-align: left; border-bottom: 1px solid var(--border); }
    th { background: #f1f5f9; font-weight: 600; color: var(--text-muted); }
  </style>
</head>
<body>

<header>
  <h1>🫀 Medical Literature Search — Indexer & Web Dashboard</h1>
  <div class="status-badge" id="headerStatus">Ready</div>
</header>

<div class="container">
  <!-- Metrics Dashboard -->
  <div class="metrics-grid">
    <div class="metric-card">
      <div class="metric-title">1. Total Documents</div>
      <div class="metric-val" id="mTotalDocs">0</div>
      <div class="metric-sub" id="mWordDocs">0 Word Docs</div>
    </div>
    <div class="metric-card">
      <div class="metric-title">2. Original File Size</div>
      <div class="metric-val" id="mOriginalSize">0 B</div>
      <div class="metric-sub" id="mPdfPages">0 PDF Pages</div>
    </div>
    <div class="metric-card">
      <div class="metric-title">3. Search DB Size</div>
      <div class="metric-val" id="mDbSize">0 B</div>
      <div class="metric-sub" id="mTextSize">0 B Text</div>
    </div>
    <div class="metric-card">
      <div class="metric-title">4. Scanned PDFs (OCR)</div>
      <div class="metric-val" id="mScannedPdfs">0</div>
      <div class="metric-sub" id="mLastIndexed">Never</div>
    </div>
  </div>

  <!-- Navigation Tabs -->
  <div class="tabs">
    <button class="tab-btn active" onclick="switchTab('tabIndexer')">1. Indexer & Scanning</button>
    <button class="tab-btn" onclick="switchTab('tabSearch')">2. Full-Text Search</button>
    <button class="tab-btn" onclick="switchTab('tabSynonyms')">3. Cardiology Synonyms</button>
    <button class="tab-btn" onclick="switchTab('tabExport')">4. Mobile PWA Export</button>
  </div>

  <!-- Tab 1: Indexer -->
  <div id="tabIndexer" class="tab-content active">
    <div class="card">
      <div class="card-title">Document Folders & Scan Controls</div>
      <div class="form-group">
        <label>Folder Paths (click Index Sample Corpus or enter path):</label>
        <input type="text" id="folderInput" placeholder="sample_corpus">
      </div>
      <div class="btn-group">
        <button class="btn" id="btnStartScan" onclick="startScan()">Start Indexing</button>
        <button class="btn btn-secondary" onclick="useSampleCorpus()">Use Sample Corpus</button>
        <button class="btn btn-secondary" onclick="controlScan('pause')">Pause</button>
        <button class="btn btn-secondary" onclick="controlScan('resume')">Resume</button>
        <button class="btn btn-danger" onclick="controlScan('cancel')">Cancel</button>
        <button class="btn btn-secondary" onclick="retryFailed()">Retry Failed</button>
      </div>

      <div class="progress-bar-container">
        <div class="progress-bar-fill" id="progressFill"></div>
      </div>
      <div class="progress-label">
        <span id="progressFile">Idle</span>
        <span id="progressPct">0%</span>
      </div>

      <div class="log-box" id="activityLogs">Indexer ready. Click 'Start Indexing' to begin.</div>
    </div>
  </div>

  <!-- Tab 2: Search -->
  <div id="tabSearch" class="tab-content">
    <div class="card">
      <div class="card-title">Instant Full-Text Search & Cardiology Exploration</div>
      <div class="search-bar">
        <input type="text" id="searchInput" placeholder="Search literature (e.g. 'Left Main', 'CTO', 'drug eluting stent', 'litho*')..." oninput="onSearchInput()">
        <button class="btn" onclick="performSearch()">Search</button>
        <div class="suggestions-list" id="suggestionsList"></div>
      </div>
      <div class="search-options">
        <label style="display:flex; align-items:center; gap:0.4rem; cursor:pointer;">
          <input type="checkbox" id="synonymCheck" checked onchange="performSearch()">
          <strong>Expand Cardiology Synonyms</strong> (e.g. LM ↔ Left Main, CTO ↔ Chronic Total Occlusion)
        </label>
        <div style="display:flex; align-items:center; gap:0.5rem; margin-left:auto;">
          <label style="margin:0;">Format:</label>
          <select id="formatFilter" onchange="performSearch()" style="width:auto; padding:0.3rem 0.6rem;">
            <option value="all">All Formats</option>
            <option value="pdf">PDF only</option>
            <option value="docx">DOCX only</option>
            <option value="doc">DOC only</option>
            <option value="txt">TXT only</option>
          </select>
        </div>
      </div>
      <div id="searchMetrics" style="font-size:0.85rem; color:var(--text-muted); margin-bottom:1rem;"></div>
      <div id="searchResultsList"></div>
    </div>
  </div>

  <!-- Tab 3: Synonyms -->
  <div id="tabSynonyms" class="tab-content">
    <div class="card">
      <div class="card-title">Cardiology Synonym & Acronym Dictionary</div>
      <p style="font-size:0.9rem; color:var(--text-muted); margin-bottom:1rem;">
        When enabled, searching for an abbreviation automatically matches all associated clinical terms and vice versa without manual typing.
      </p>
      <div style="display:flex; gap:0.5rem; margin-bottom:1.5rem;">
        <input type="text" id="newSynTerm" placeholder="Acronym (e.g. TAVR)" style="max-width:200px;">
        <input type="text" id="newSynExpanded" placeholder="Expansion (e.g. transcatheter aortic valve replacement, TAVI)">
        <button class="btn" onclick="addSynonym()">Add Synonym</button>
      </div>
      <table>
        <thead>
          <tr>
            <th style="width:25%;">Term / Acronym</th>
            <th>Expansions & Clinical Synonyms</th>
          </tr>
        </thead>
        <tbody id="synonymsTableBody">
          <tr><td colspan="2">Loading synonyms...</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- Tab 4: Export -->
  <div id="tabExport" class="tab-content">
    <div class="card">
      <div class="card-title">Export Portable Database for Mobile PWA</div>
      <p style="font-size:0.9rem; color:var(--text-muted); margin-bottom:1.2rem;">
        Export a high-performance, compressed search database for instant offline full-text search on iPhone, iPad, and Android without requiring the original 16 GB document files.
      </p>
      <div class="form-group">
        <label>Export Package Type:</label>
        <select id="exportType" style="max-width:350px;">
          <option value="search-only">Search-Only Compact DB (Recommended for Mobile PWA)</option>
          <option value="full">Full Database Snapshot (All Documents & Logs)</option>
          <option value="delta">Incremental Delta Package (.json)</option>
        </select>
      </div>
      <div class="form-group">
        <label style="display:flex; align-items:center; gap:0.4rem; cursor:pointer;">
          <input type="checkbox" id="exportCompress" checked>
          <strong>Compress with Zstandard (ZSTD)</strong> — Achieves >95% reduction for rapid mobile downloads
        </label>
      </div>
      <button class="btn" id="btnExport" onclick="runExport()" style="font-size:1rem; padding:0.7rem 1.5rem;">
        🚀 Generate & Download Export
      </button>

      <div id="exportResult" style="margin-top:1.5rem; display:none;"></div>
    </div>
  </div>
</div>

<script>
  let debounceTimer = null;

  function switchTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    document.getElementById(tabId).classList.add('active');
    event.target.classList.add('active');
    if (tabId === 'tabSynonyms') loadSynonyms();
  }

  async function loadStats() {
    try {
      const res = await fetch('/api/stats');
      const data = await res.json();
      document.getElementById('mTotalDocs').textContent = data.total_documents.toLocaleString();
      document.getElementById('mWordDocs').textContent = data.number_of_word_documents.toLocaleString() + ' Word Docs';
      document.getElementById('mOriginalSize').textContent = data.total_original_file_size_fmt;
      document.getElementById('mPdfPages').textContent = data.number_of_pdf_pages.toLocaleString() + ' PDF Pages';
      document.getElementById('mDbSize').textContent = data.database_size_fmt;
      document.getElementById('mTextSize').textContent = data.extracted_text_size_fmt + ' Text';
      document.getElementById('mScannedPdfs').textContent = data.number_of_scanned_pdfs.toLocaleString();
      document.getElementById('mLastIndexed').textContent = data.last_indexing_date || 'Never';
    } catch (e) {
      console.error(e);
    }
  }

  async function checkProgress() {
    try {
      const res = await fetch('/api/scan/progress');
      const p = await res.json();
      document.getElementById('headerStatus').textContent = p.status.toUpperCase();
      document.getElementById('progressFile').textContent = p.message || 'Idle';
      if (p.total > 0) {
        const pct = Math.round((p.current / p.total) * 100);
        document.getElementById('progressFill').style.width = pct + '%';
        document.getElementById('progressPct').textContent = pct + '% (' + p.current + '/' + p.total + ')';
      }
      if (p.logs && p.logs.length > 0) {
        const box = document.getElementById('activityLogs');
        box.textContent = p.logs.join('\\n');
        box.scrollTop = box.scrollHeight;
      }
      if (p.is_indexing) {
        setTimeout(checkProgress, 800);
      } else {
        loadStats();
      }
    } catch (e) {
      console.error(e);
    }
  }

  function useSampleCorpus() {
    document.getElementById('folderInput').value = 'sample_corpus';
  }

  async function startScan() {
    const val = document.getElementById('folderInput').value.trim();
    const folders = val ? [val] : [];
    document.getElementById('activityLogs').textContent = 'Starting indexing scan...';
    const res = await fetch('/api/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folders })
    });
    const d = await res.json();
    if (d.error) {
      alert(d.error);
    } else {
      setTimeout(checkProgress, 500);
    }
  }

  async function controlScan(action) {
    await fetch('/api/scan/control', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action })
    });
    checkProgress();
  }

  async function retryFailed() {
    await fetch('/api/retry', { method: 'POST' });
    setTimeout(checkProgress, 500);
  }

  function onSearchInput() {
    clearTimeout(debounceTimer);
    const q = document.getElementById('searchInput').value.trim();
    if (q.length < 2) {
      document.getElementById('suggestionsList').style.display = 'none';
      return;
    }
    debounceTimer = setTimeout(async () => {
      const res = await fetch('/api/suggest?q=' + encodeURIComponent(q));
      const d = await res.json();
      const list = document.getElementById('suggestionsList');
      if (d.suggestions && d.suggestions.length > 0) {
        list.innerHTML = d.suggestions.map(s => 
          `<div class="suggestion-item" onclick="selectSuggestion('${(s.text || s.term || '').replace(/'/g, "\\\\'")}')">${s.display || s.text || s.term}</div>`
        ).join('');
        list.style.display = 'block';
      } else {
        list.style.display = 'none';
      }
    }, 150);
  }

  function selectSuggestion(term) {
    document.getElementById('searchInput').value = term;
    document.getElementById('suggestionsList').style.display = 'none';
    performSearch();
  }

  async function performSearch() {
    const q = document.getElementById('searchInput').value.trim();
    document.getElementById('suggestionsList').style.display = 'none';
    if (!q) return;

    const syn = document.getElementById('synonymCheck').checked;
    const fmt = document.getElementById('formatFilter').value;
    const url = `/api/search?q=${encodeURIComponent(q)}&synonyms=${syn}&format=${encodeURIComponent(fmt)}`;

    const res = await fetch(url);
    const d = await res.json();

    const metricsEl = document.getElementById('searchMetrics');
    metricsEl.textContent = `Found ${d.total_count} results in ${d.execution_time_ms.toFixed(1)} ms. Parsed FTS5: ${d.parsed_query}`;

    const listEl = document.getElementById('searchResultsList');
    if (d.results.length === 0) {
      listEl.innerHTML = '<div style="padding:2rem; text-align:center; color:var(--text-muted);">No documents matched your query.</div>';
      return;
    }

    listEl.innerHTML = d.results.map(r => `
      <div class="result-card">
        <div class="result-header">
          <span class="result-title">${r.title || r.filename}</span>
          <span class="result-badge">${r.file_type}</span>
        </div>
        <div class="result-meta">
          📁 ${r.filename} &bull; Page ${r.page_number} &bull; Score: ${r.rank_score.toFixed(2)}
        </div>
        <div class="result-snippet">${r.snippet_html}</div>
      </div>
    `).join('');
  }

  async function loadSynonyms() {
    const res = await fetch('/api/synonyms');
    const d = await res.json();
    const tbody = document.getElementById('synonymsTableBody');
    tbody.innerHTML = d.synonyms.map(s => `
      <tr>
        <td><strong>${s.term}</strong></td>
        <td>${s.expansion}</td>
      </tr>
    `).join('');
  }

  async function addSynonym() {
    const term = document.getElementById('newSynTerm').value.trim();
    const expanded = document.getElementById('newSynExpanded').value.trim();
    if (!term || !expanded) return;
    await fetch('/api/synonyms', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ term, expanded })
    });
    document.getElementById('newSynTerm').value = '';
    document.getElementById('newSynExpanded').value = '';
    loadSynonyms();
  }

  async function runExport() {
    const type = document.getElementById('exportType').value;
    const compress = document.getElementById('exportCompress').checked;
    const btn = document.getElementById('btnExport');
    const resDiv = document.getElementById('exportResult');
    
    btn.disabled = true;
    btn.textContent = 'Generating Export...';
    resDiv.style.display = 'none';

    try {
      const res = await fetch('/api/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type, compress })
      });
      const d = await res.json();
      if (d.error) {
        alert('Export error: ' + d.error);
      } else {
        resDiv.style.display = 'block';
        resDiv.innerHTML = `
          <div style="background:#ecfdf5; border:1px solid #6ee7b7; border-radius:8px; padding:1.2rem;">
            <h3 style="color:#065f46; margin-bottom:0.5rem;">✅ Export Generated Successfully</h3>
            <p><strong>File:</strong> ${d.filename}</p>
            <p><strong>Size:</strong> ${d.file_size_fmt} (Compressed from ${d.uncompressed_size_fmt}, ${d.compression_ratio})</p>
            <p><strong>SHA-256:</strong> <code style="font-size:0.8rem;">${d.sha256}</code></p>
            <div style="margin-top:1rem;">
              <a href="${d.download_url}" download class="btn" style="text-decoration:none; display:inline-block;">
                📥 Download ${d.filename}
              </a>
            </div>
          </div>
        `;
      }
    } catch (e) {
      alert('Error during export: ' + e);
    } finally {
      btn.disabled = false;
      btn.textContent = '🚀 Generate & Download Export';
    }
  }

  // Initial load
  loadStats();
  setInterval(loadStats, 10000);
</script>
</body>
</html>
"""


def run_web_server(host: str = "0.0.0.0", port: int = 8080, db_path: Path = DEFAULT_DB_PATH, open_browser: bool = True) -> None:
    """Start the HTTP server on the specified host and port."""
    global _state
    _state = WebState(db_path)

    server = ThreadingHTTPServer((host, port), MedicalSearchHandler)
    logger.info(f"Web Dashboard running at http://{host}:{port}/")
    print("\n" + "=" * 65)
    print("      MEDICAL LITERATURE SEARCH — WEB DASHBOARD & API")
    print("=" * 65)
    print(f"  URL:           http://localhost:{port}/")
    if host == "0.0.0.0":
        print(f"  Network:       http://0.0.0.0:{port}/")
    print(f"  Database:      {Path(db_path).resolve()}")
    print("=" * 65)
    print("  Press Ctrl+C to stop the web server.\n")

    if open_browser:
        def try_open():
            time.sleep(0.6)
            try:
                import webbrowser
                webbrowser.open(f"http://localhost:{port}/")
            except Exception:
                pass
        threading.Thread(target=try_open, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping web server...")
        server.server_close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Medical Literature Search Web Dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="Path to SQLite database")
    args = parser.parse_args()

    run_web_server(host=args.host, port=args.port, db_path=args.db)
