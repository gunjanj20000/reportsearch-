"""
Self-contained, zero-dependency Web GUI and REST API for Universal Document Search.
Provides complete indexing, live stats, full-text document search, and mobile database export.
Works in any browser without requiring PySide6/Qt or GUI libraries.
"""

from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import (
    logger,
    DEFAULT_DB_PATH,
    EXPORTS_DIR,
    find_libreoffice_binary,
    find_tesseract_binary,
    format_bytes,
    resolve_network_path,
    is_archive_file,
)
from .database.connection import DatabaseManager
from .engine.indexer_engine import IndexerEngine
from .search.search_service import SearchService, SearchResponse
from .search.suggestions import SuggestionService
from .search.synonyms import SynonymManager
from .export.exporter import ExportManager


def open_native_folder_dialog(initial_dir: Optional[str] = None) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Attempts to open a native OS folder dialog using system tools:
    - Linux: Zenity / KDialog / Tkinter
    - Windows: PowerShell FolderBrowserDialog / Tkinter
    - macOS: AppleScript osascript / Tkinter
    Returns (supported, selected_path, error_message).
    """
    if not initial_dir or not os.path.isdir(initial_dir):
        initial_dir = str(Path.home())

    # 1. Linux / Unix
    if sys.platform.startswith("linux") or "bsd" in sys.platform:
        zenity = shutil.which("zenity")
        if zenity and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            try:
                res = subprocess.run(
                    [zenity, "--file-selection", "--directory", "--title=Select Folder to Index", f"--filename={initial_dir}/"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120
                )
                if res.returncode == 0 and res.stdout.strip():
                    return True, res.stdout.strip(), None
                return True, None, "Selection cancelled"
            except Exception as e:
                logger.warning(f"Zenity execution failed: {e}")

        kdialog = shutil.which("kdialog")
        if kdialog and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            try:
                res = subprocess.run(
                    [kdialog, "--getexistingdirectory", initial_dir, "--title", "Select Folder to Index"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120
                )
                if res.returncode == 0 and res.stdout.strip():
                    return True, res.stdout.strip(), None
                return True, None, "Selection cancelled"
            except Exception as e:
                logger.warning(f"KDialog execution failed: {e}")

    # 2. Windows
    elif sys.platform == "win32":
        ps_cmd = (
            f"[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
            f"$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
            f"$f.Description = 'Select Folder to Index'; "
            f"$f.SelectedPath = '{initial_dir}'; "
            f"if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{ Write-Host $f.SelectedPath }}"
        )
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120
            )
            if res.returncode == 0 and res.stdout.strip():
                return True, res.stdout.strip(), None
            return True, None, "Selection cancelled"
        except Exception as e:
            logger.warning(f"PowerShell FolderBrowserDialog failed: {e}")

    # 3. macOS
    elif sys.platform == "darwin":
        osa_cmd = f'POSIX path of (choose folder with prompt "Select Folder to Index:" default location "{initial_dir}")'
        try:
            res = subprocess.run(
                ["osascript", "-e", osa_cmd],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120
            )
            if res.returncode == 0 and res.stdout.strip():
                return True, res.stdout.strip(), None
            return True, None, "Selection cancelled"
        except Exception as e:
            logger.warning(f"AppleScript dialog failed: {e}")

    # 4. Tkinter fallback if graphical display is available
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or sys.platform in ("win32", "darwin"):
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected = filedialog.askdirectory(initialdir=initial_dir, title="Select Folder to Index")
            root.destroy()
            if selected:
                return True, selected, None
            return True, None, "Selection cancelled"
        except Exception:
            pass

    return False, None, "Native OS file dialog not supported on this host environment without desktop display."


def get_attached_storage_devices() -> List[Dict[str, str]]:
    """
    Detect connected removable storage devices:
    - USB pendrives / flash drives
    - External hard drives / SSDs
    - SD cards
    - Mounts under /media, /run/media, and /mnt
    - Windows drive letters
    """
    devices: List[Dict[str, str]] = []
    seen = set()
    excluded = ("/boot", "/sys", "/proc", "/dev", "/run/lock", "/run/systemd")

    # 1. Linux removable media detection
    if sys.platform.startswith("linux") or "bsd" in sys.platform:
        candidate_roots = ["/media", "/run/media", "/mnt"]
        for base in ["/media", "/run/media"]:
            if os.path.exists(base):
                try:
                    for entry in os.scandir(base):
                        if entry.is_dir(follow_symlinks=False):
                            candidate_roots.append(entry.path)
                except Exception:
                    pass

        for root in candidate_roots:
            if os.path.exists(root) and os.path.isdir(root):
                try:
                    for entry in os.scandir(root):
                        if entry.is_dir(follow_symlinks=False):
                            full_path = str(Path(entry.path).resolve())
                            if full_path not in seen and not any(full_path.startswith(ex) for ex in excluded):
                                name_lower = entry.name.lower()
                                icon = "🔌" if any(w in name_lower for w in ["usb", "pen", "flash", "thumb", "sd"]) else "💾"
                                devices.append({
                                    "name": f"{icon} {entry.name}",
                                    "path": full_path,
                                    "type": "removable"
                                })
                                seen.add(full_path)
                except Exception:
                    pass

        # Also inspect /proc/mounts for external block devices
        if os.path.exists("/proc/mounts"):
            target_fs = {"vfat", "exfat", "ntfs", "ntfs3", "fuseblk", "ext4", "iso9660"}
            try:
                with open("/proc/mounts", "r") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) >= 3:
                            dev, mnt, fst = parts[0], parts[1], parts[2]
                            if (dev.startswith(("/dev/sd", "/dev/mmc", "/dev/disk")) or mnt.startswith(("/media", "/run/media", "/mnt"))) and fst in target_fs:
                                if mnt not in seen and not any(mnt.startswith(ex) for ex in excluded) and mnt not in ("/", "/home", "/tmp"):
                                    label = os.path.basename(mnt) or mnt
                                    icon = "🔌" if any(w in label.lower() for w in ["usb", "pen", "flash", "sd"]) else "💾"
                                    devices.append({
                                        "name": f"{icon} {label} ({fst})",
                                        "path": str(Path(mnt).resolve()),
                                        "type": "removable"
                                    })
                                    seen.add(mnt)
            except Exception:
                pass

    # 2. Windows Drive Letters
    elif sys.platform == "win32":
        import string
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\\\"
            if os.path.exists(drive):
                label = f"💾 Drive {letter}:"
                devices.append({
                    "name": label,
                    "path": drive,
                    "type": "drive"
                })

    return devices


def get_system_network_mounts() -> List[Dict[str, str]]:
    """
    Detect active network mounts, CIFS/Samba shares, NFS exports, and GVFS connections.
    """
    mounts: List[Dict[str, str]] = []
    seen_paths = set()

    # 1. Linux /proc/mounts
    if os.path.exists("/proc/mounts"):
        net_fs = {"cifs", "smbfs", "nfs", "nfs4", "fuse.gvfsd-fuse", "sshfs", "9p", "davfs"}
        try:
            with open("/proc/mounts", "r") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 3:
                        device, mountpoint, fstype = parts[0], parts[1], parts[2]
                        if fstype in net_fs:
                            if os.path.isdir(mountpoint) and mountpoint not in seen_paths:
                                seen_paths.add(mountpoint)
                                label = f"🌐 {os.path.basename(mountpoint) or mountpoint} ({fstype})"
                                mounts.append({"name": label, "path": mountpoint, "type": fstype, "device": device})
        except Exception:
            pass

    # 2. Linux GNOME / Ubuntu GVFS SMB Mounts
    user_id = os.getuid() if hasattr(os, "getuid") else 1000
    gvfs_dir = Path(f"/run/user/{user_id}/gvfs")
    if gvfs_dir.exists():
        try:
            for entry in gvfs_dir.iterdir():
                if entry.is_dir() and str(entry) not in seen_paths:
                    seen_paths.add(str(entry))
                    clean_name = entry.name.replace("smb-share:", "SMB: ").replace("sftp:", "SFTP: ")
                    mounts.append({
                        "name": f"🌐 {clean_name}",
                        "path": str(entry.resolve()),
                        "type": "gvfs",
                        "device": entry.name
                    })
        except Exception:
            pass

    # 3. Common network mount directories if populated
    for common_dir in ["/mnt", "/media"]:
        p = Path(common_dir)
        if p.exists():
            try:
                for sub in p.iterdir():
                    if sub.is_dir() and str(sub) not in seen_paths:
                        seen_paths.add(str(sub))
                        mounts.append({
                            "name": f"📁 {sub.name} ({common_dir})",
                            "path": str(sub.resolve()),
                            "type": "mount",
                            "device": str(sub)
                        })
            except Exception:
                pass

    # 4. Windows Mapped Network Drives
    if sys.platform == "win32":
        import string
        for letter in string.ascii_uppercase[2:]:
            drive = f"{letter}:\\\\"
            if os.path.exists(drive):
                try:
                    mounts.append({
                        "name": f"💾 Drive {letter}:",
                        "path": drive,
                        "type": "drive",
                        "device": drive
                    })
                except Exception:
                    pass

    return mounts


def test_storage_path(path_str: str) -> Dict[str, Any]:
    """
    Validates any local folder, USB drive, external hard disk, or network share / UNC path.
    Tests accessibility, counts files/documents, and resolves GVFS/SMB mappings.
    """
    clean = path_str.strip()
    if not clean:
        return {"valid": False, "error": "Path cannot be empty."}

    resolved = resolve_network_path(clean)
    p = Path(resolved)

    # If doesn't exist, try gio mount if on Linux and it starts with smb:// or \\
    if not p.exists() and sys.platform.startswith("linux") and (clean.startswith(("\\\\", "//", "smb://"))):
        smb_url = clean
        if clean.startswith(("\\\\", "//")):
            smb_url = "smb://" + clean.lstrip("\\/").replace("\\", "/")

        gio = shutil.which("gio")
        if gio:
            try:
                subprocess.run([gio, "mount", smb_url], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=8)
                resolved_after = resolve_network_path(clean)
                p = Path(resolved_after)
                if p.exists() and p.is_dir():
                    resolved = resolved_after
            except Exception:
                pass

    if not p.exists():
        return {
            "valid": False,
            "resolved_path": resolved,
            "error": f"Folder '{clean}' could not be reached or does not exist. Ensure the drive or network share is connected."
        }

    if not p.is_dir() and not is_archive_file(p):
        return {
            "valid": False,
            "resolved_path": resolved,
            "error": f"'{clean}' is not a directory or supported compressed archive (.zip, .tar.gz, etc.)."
        }

    # If it is a compressed archive
    if is_archive_file(p):
        from .scanner.archive_scanner import ArchiveScanner
        ascanner = ArchiveScanner()
        docs = ascanner.inspect_and_extract(p)
        return {
            "valid": True,
            "resolved_path": str(p.resolve()),
            "doc_count_est": len(docs),
            "sample_files": [Path(d.member_name).name for d in docs[:4]],
            "is_archive": True
        }

    doc_count = 0
    sample_files = []
    supported_exts = {".pdf", ".docx", ".doc", ".txt"}
    try:
        for root, _, files in os.walk(resolved):
            for f in files:
                ext = Path(f).suffix.lower()
                if ext in supported_exts:
                    doc_count += 1
                    if len(sample_files) < 4:
                        sample_files.append(f)
    except PermissionError:
        return {
            "valid": False,
            "resolved_path": resolved,
            "error": f"Permission denied accessing '{clean}'. Please check storage device permissions."
        }
    except Exception as e:
        return {
            "valid": False,
            "resolved_path": resolved,
            "error": f"Error accessing folder: {e}"
        }

    return {
        "valid": True,
        "original_path": clean,
        "resolved_path": str(p.resolve()),
        "doc_count_est": doc_count,
        "sample_files": sample_files,
        "message": f"Successfully connected! Found {doc_count} medical documents in this folder."
    }


def sanitize_table_text(text: str) -> str:
    """Deduplicate adjacent duplicated table cells in pipe-delimited table rows."""
    if not text or "|" not in text:
        return text
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            deduped = []
            for p in parts:
                if not p:
                    continue
                norm = " ".join(p.split())
                if not deduped or " ".join(deduped[-1].split()) != norm:
                    deduped.append(p)
            if deduped:
                cleaned_lines.append(" | ".join(deduped))
        else:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


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

        # Wire progress callback
        def on_engine_progress(cur: int, tot: int, fn: str, msg: str):
            with self.progress_lock:
                self.progress_current = cur
                self.progress_total = tot
                self.progress_filename = fn
                self.progress_message = msg
                if msg:
                    self.activity_logs.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
                    if len(self.activity_logs) > 500:
                        self.activity_logs.pop(0)

        self.engine.on_progress = on_engine_progress


_state: Optional[WebState] = None


class MedicalSearchHandler(BaseHTTPRequestHandler):
    """Zero-dependency HTTP Handler providing JSON REST API and modern SPA."""

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress standard HTTP server access logs to stdout to keep console clean."""
        pass

    def send_json(self, data: Any, status: int = 200) -> None:
        """Serialize data to JSON and send response."""
        resp = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(resp)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(resp)

    def do_OPTIONS(self) -> None:
        """Handle CORS pre-flight requests."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def serve_static_file(self, file_path: Path, content_type: Optional[str] = None) -> None:
        """Serve static asset with appropriate MIME headers and OPFS security headers."""
        if not file_path.is_file():
            self.send_error(404, "File Not Found")
            return

        ext = file_path.suffix.lower()
        if content_type is None:
            mime_map = {
                ".html": "text/html; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".mjs": "application/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".wasm": "application/wasm",
                ".webmanifest": "application/manifest+json; charset=utf-8",
                ".json": "application/json; charset=utf-8",
                ".svg": "image/svg+xml",
                ".png": "image/png",
                ".ico": "image/x-icon",
                ".zst": "application/zstd",
                ".db": "application/octet-stream",
            }
            content_type = mime_map.get(ext, "application/octet-stream")

        try:
            with open(file_path, "rb") as f:
                data = f.read()
        except OSError:
            self.send_error(500, "Failed to read file")
            return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        # COOP & COEP required for SQLite WASM + OPFS
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Access-Control-Allow-Origin", "*")

        if ext in (".html", ".webmanifest") or file_path.name == "sw.js":
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        else:
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")

        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        params = urllib.parse.parse_qs(parsed_url.query)

        # 1. Dashboard Stats API
        if path == "/api/stats":
            stats = _state.db.get_dashboard_stats()
            lo_bin = find_libreoffice_binary()
            tess_bin = find_tesseract_binary()

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
                "last_indexing_date": stats.last_indexing_date or "Never",
                "libreoffice": lo_bin is not None,
                "tesseract": tess_bin is not None,
                "is_indexing": _state.is_indexing
            })
            return

        # 2. Indexing Progress Poll API
        if path == "/api/scan/progress":
            with _state.progress_lock:
                self.send_json({
                    "is_indexing": _state.is_indexing,
                    "current": _state.progress_current,
                    "total": _state.progress_total,
                    "filename": _state.progress_filename,
                    "message": _state.progress_message,
                    "logs": _state.activity_logs[-30:]
                })
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

        # 8. Filesystem Browse API (Local, USB Pendrives, External HDDs, and Network Mounts)
        if path == "/api/fs/browse":
            req_dir = params.get("path", [""])[0].strip()
            if not req_dir:
                target_dir = Path.home().resolve()
            else:
                resolved_p = resolve_network_path(req_dir)
                target_dir = Path(resolved_p).resolve()

            if not target_dir.exists() or not target_dir.is_dir():
                target_dir = Path.home().resolve()

            subdirs = []
            try:
                for entry in sorted(os.scandir(target_dir), key=lambda e: e.name.lower()):
                    if entry.name.startswith("."):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        try:
                            subdirs.append({
                                "name": entry.name,
                                "path": str(Path(entry.path).resolve()),
                                "is_archive": False
                            })
                        except Exception:
                            continue
                    elif is_archive_file(entry.name):
                        try:
                            subdirs.append({
                                "name": f"📦 {entry.name}",
                                "path": str(Path(entry.path).resolve()),
                                "is_archive": True
                            })
                        except Exception:
                            continue
            except (PermissionError, OSError) as e:
                logger.warning(f"Cannot read directory {target_dir}: {e}")

            # Breadcrumbs
            breadcrumbs = []
            curr = target_dir
            while curr != curr.parent:
                breadcrumbs.append({"name": curr.name or str(curr), "path": str(curr)})
                curr = curr.parent
            breadcrumbs.append({"name": str(curr), "path": str(curr)})
            breadcrumbs.reverse()

            # Helpful local shortcuts
            home = Path.home().resolve()
            raw_shortcuts = [
                {"name": "🏠 Home (~)", "path": str(home)},
                {"name": "📄 Documents", "path": str(home / "Documents")},
                {"name": "📥 Downloads", "path": str(home / "Downloads")},
                {"name": "🖥️ Desktop", "path": str(home / "Desktop")},
            ]


            if sys.platform != "win32":
                raw_shortcuts.append({"name": "💾 Root (/)", "path": "/"})
                if Path("/media").exists():
                    raw_shortcuts.append({"name": "🔌 /media", "path": "/media"})
                if Path("/mnt").exists():
                    raw_shortcuts.append({"name": "🔌 /mnt", "path": "/mnt"})
            else:
                import string
                for letter in string.ascii_uppercase:
                    dp = letter + ":\\\\"
                    if os.path.exists(dp):
                        raw_shortcuts.append({"name": f"💾 Drive {letter}:", "path": dp})

            valid_shortcuts = [s for s in raw_shortcuts if os.path.isdir(s["path"])]

            # Detect attached USB drives and external hard drives
            attached_devices = get_attached_storage_devices()

            # Detect network mounts
            network_mounts = get_system_network_mounts()

            self.send_json({
                "current_path": str(target_dir),
                "parent_path": str(target_dir.parent) if target_dir.parent != target_dir else None,
                "breadcrumbs": breadcrumbs,
                "shortcuts": valid_shortcuts,
                "attached_devices": attached_devices,
                "network_mounts": network_mounts,
                "subdirectories": subdirs
            })
            return

        # 9. Active Network Mounts & Devices API
        if path in ("/api/fs/network_mounts", "/api/fs/devices"):
            self.send_json({
                "devices": get_attached_storage_devices(),
                "mounts": get_system_network_mounts()
            })
            return

        # 10. Document Page Note API (Read-only, 0 bytes added to index)
        if path == "/api/document/page":
            try:
                doc_id = int(params.get("doc_id", ["0"])[0])
                page_num = int(params.get("page", ["1"])[0])
            except ValueError:
                self.send_json({"error": "Invalid doc_id or page parameter."}, status=400)
                return

            conn = _state.db.get_connection()
            doc_row = conn.execute(
                "SELECT filename, extension, source_path, page_count FROM documents WHERE document_id = ?",
                (doc_id,)
            ).fetchone()

            if not doc_row:
                self.send_json({"error": "Document not found."}, status=404)
                return

            filename, extension, source_path, page_count = doc_row

            # Fetch page content directly from SQLite without writing anything
            page_row = conn.execute(
                "SELECT extracted_text FROM document_pages WHERE document_id = ? AND page_number = ?",
                (doc_id, page_num)
            ).fetchone()

            page_content = ""
            if page_row and page_row[0]:
                page_content = page_row[0]
            else:
                # Fallback to document_paragraphs if document_pages is empty
                paras = conn.execute(
                    "SELECT paragraph_text FROM document_paragraphs WHERE document_id = ? AND page_number = ? ORDER BY paragraph_number",
                    (doc_id, page_num)
                ).fetchall()
                if paras:
                    page_content = "\n\n".join(p[0] for p in paras if p[0])

            paras_rows = conn.execute(
                "SELECT paragraph_text FROM document_paragraphs WHERE document_id = ? AND page_number = ? ORDER BY paragraph_number",
                (doc_id, page_num)
            ).fetchall()
            paragraphs = [p[0] for p in paras_rows if p[0]]

            if not page_content and paragraphs:
                page_content = "\n\n".join(paragraphs)

            if page_content:
                page_content = sanitize_table_text(page_content)
            paragraphs = [sanitize_table_text(p) for p in paragraphs if p]

            is_archive = "#" in source_path
            archive_name = None
            member_path = None
            if is_archive:
                parts = source_path.split("#", 1)
                archive_name = Path(parts[0]).name
                member_path = parts[1]

            doc_title = filename
            try:
                title_row = conn.execute(
                    "SELECT title FROM search_index WHERE document_id = ? AND title IS NOT NULL LIMIT 1",
                    (doc_id,)
                ).fetchone()
                if title_row and title_row[0]:
                    doc_title = title_row[0]
            except Exception:
                pass

            self.send_json({
                "document_id": doc_id,
                "filename": filename,
                "doc_title": doc_title,
                "extension": extension.replace(".", "").upper(),
                "source_path": source_path,
                "page_number": page_num,
                "total_pages": max(page_count or 1, 1),
                "content": page_content,
                "paragraphs": paragraphs,
                "is_archive": is_archive,
                "archive_name": archive_name,
                "member_path": member_path
            })
            return

        # 11. Serve Embedded Modern Web App HTML
        if path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            html_bytes = SPA_HTML.encode("utf-8")
            self.send_header("Content-Length", str(len(html_bytes)))
            self.end_headers()
            self.wfile.write(html_bytes)
            return

        # 12. Universal Mobile Search React + TypeScript PWA (Phase 4 & 5)
        pwa_dist = Path(__file__).resolve().parent.parent / "pwa" / "dist"

        # PWA entry points
        if path in ("/pwa", "/pwa/", "/mobile", "/mobile/"):
            index_path = pwa_dist / "index.html"
            if index_path.exists():
                self.serve_static_file(index_path, "text/html; charset=utf-8")
                return

        # PWA subpaths: /pwa/... or /mobile/...
        if path.startswith(("/pwa/", "/mobile/")):
            rel_sub = path.split("/", 2)[-1]
            candidate = (pwa_dist / rel_sub).resolve()
            if candidate.is_file() and candidate.is_relative_to(pwa_dist):
                self.serve_static_file(candidate)
                return
            index_path = pwa_dist / "index.html"
            if index_path.exists():
                self.serve_static_file(index_path, "text/html; charset=utf-8")
                return

        # Root static assets referenced by PWA
        if pwa_dist.exists() and path != "/":
            clean_rel = path.lstrip("/")
            candidate = (pwa_dist / clean_rel).resolve()
            if candidate.is_file() and candidate.is_relative_to(pwa_dist):
                self.serve_static_file(candidate)
                return

        # Compact database export direct download
        if path in ("/exports/medical_search_compact.db.zst", "/api/db/compact.zst"):
            compact_path = Path(__file__).resolve().parent.parent / "exports" / "medical_search_compact.db.zst"
            if compact_path.exists():
                self.serve_static_file(compact_path, "application/zstd")
                return

        if path in ("/exports/medical_search_compact.db", "/api/db/compact.db"):
            compact_db_path = Path(__file__).resolve().parent.parent / "exports" / "medical_search_compact.db"
            if compact_db_path.exists():
                self.serve_static_file(compact_db_path, "application/octet-stream")
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
                self.send_json({"error": "No folder selected. Please click 'Browse Folder...' to choose a folder or compressed archive to index."}, status=400)
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
                self.send_json({"error": "Invalid action. Supported: pause, resume, cancel."}, status=400)
            return

        # 3. Retry Failed Documents
        if path == "/api/retry":
            def run_retry_worker():
                _state.is_indexing = True
                try:
                    _state.engine.retry_failed()
                except Exception as e:
                    logger.error(f"Error in web retry scan: {e}")
                finally:
                    _state.is_indexing = False

            thread = threading.Thread(target=run_retry_worker, daemon=True)
            thread.start()
            self.send_json({"success": True, "message": "Retrying failed documents."})
            return

        # 4. Clear Database
        if path == "/api/clear":
            if _state.is_indexing:
                self.send_json({"error": "Cannot clear database while indexing is running."}, status=400)
                return
            _state.engine.clear_database()
            self.send_json({"success": True, "message": "Database reset successfully."})
            return

        # 5. Add / Update Synonym
        if path == "/api/synonyms":
            term = data.get("term", "").strip()
            expanded = data.get("expanded", "").strip()
            if not term or not expanded:
                self.send_json({"error": "Term and expansion cannot be empty."}, status=400)
                return
            _state.synonym_manager.add_synonym(term, expanded)
            self.send_json({"success": True, "term": term, "expanded": expanded})
            return

        # 6. Native OS Folder Dialog API
        if path == "/api/fs/native_dialog":
            initial_dir = data.get("initial_dir", "")
            supported, selected_path, err_msg = open_native_folder_dialog(initial_dir)
            self.send_json({
                "supported": supported,
                "path": selected_path,
                "error": err_msg
            })
            return

        # 7. Storage Path & Network Share Verification API
        if path in ("/api/fs/network_check", "/api/fs/check_path"):
            test_path = data.get("path", "").strip()
            res = test_storage_path(test_path)
            self.send_json(res)
            return

        # 8. Generate Portable Database Export
        if path == "/api/export":
            export_type = data.get("type", "compact").lower()
            compress = data.get("compress", True)
            since = data.get("since")

            timestamp = time.strftime("%Y%m%d_%H%M%S")
            try:
                if export_type == "full":
                    target_file = EXPORTS_DIR / f"medical_full_{timestamp}.db"
                    res = _state.export_manager.export_full_database(target_file, compress=compress)
                elif export_type == "compact":
                    target_file = EXPORTS_DIR / f"medical_search_compact_{timestamp}.db"
                    res = _state.export_manager.export_search_only_database(target_file, compress=compress)
                else:
                    target_file = EXPORTS_DIR / f"medical_delta_{timestamp}.json"
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


SPA_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Universal Document Search — Desktop Dashboard</title>
  <style>
    :root {
      --primary: #0284c7;
      --primary-dark: #0369a1;
      --primary-light: #e0f2fe;
      --bg: #f8fafc;
      --card-bg: #ffffff;
      --text: #0f172a;
      --text-muted: #64748b;
      --border: #e2e8f0;
      --border-focus: #38bdf8;
      --accent-green: #10b981;
      --accent-green-dark: #059669;
      --accent-amber: #f59e0b;
      --accent-red: #ef4444;
      --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);
      --shadow: 0 4px 6px -1px rgb(0 0 0 / 0.08), 0 2px 4px -2px rgb(0 0 0 / 0.06);
      --shadow-lg: 0 20px 25px -5px rgb(0 0 0 / 0.12), 0 8px 10px -6px rgb(0 0 0 / 0.08);
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
    body { background-color: var(--bg); color: var(--text); line-height: 1.5; }
    
    header {
      background: #0f172a;
      color: white;
      padding: 1rem 1.5rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 3px solid var(--primary);
    }
    header h1 {
      font-size: 1.25rem;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 0.6rem;
    }
    header .status-badge {
      font-size: 0.82rem;
      background: #1e293b;
      color: #38bdf8;
      padding: 0.25rem 0.75rem;
      border-radius: 9999px;
      border: 1px solid #334155;
      font-weight: 600;
    }
    .container { max-width: 1200px; margin: 1.5rem auto; padding: 0 1rem; }
    
    /* Navigation Tabs */
    .tabs { display: flex; gap: 0.5rem; border-bottom: 2px solid var(--border); margin-bottom: 1.5rem; }
    .tab-btn {
      background: none;
      border: none;
      padding: 0.7rem 1.25rem;
      font-size: 0.95rem;
      font-weight: 600;
      color: var(--text-muted);
      cursor: pointer;
      border-bottom: 3px solid transparent;
      margin-bottom: -2px;
      transition: all 0.15s;
    }
    .tab-btn:hover { color: var(--primary); }
    .tab-btn.active { color: var(--primary); border-bottom-color: var(--primary); }
    .tab-content { display: none; }
    .tab-content.active { display: block; }

    /* Dashboard Metrics Cards */
    .metrics-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 1rem;
      margin-bottom: 1.5rem;
    }
    .metric-card {
      background: var(--card-bg);
      border-radius: 10px;
      padding: 1.1rem 1.25rem;
      border: 1px solid var(--border);
      box-shadow: var(--shadow-sm);
    }
    .metric-title {
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      font-weight: 700;
      margin-bottom: 0.35rem;
    }
    .metric-val { font-size: 1.6rem; font-weight: 700; color: var(--text); }
    .metric-sub { font-size: 0.8rem; color: var(--text-muted); margin-top: 0.25rem; }

    /* Cards & Controls */
    .card {
      background: var(--card-bg);
      border-radius: 10px;
      padding: 1.5rem;
      border: 1px solid var(--border);
      box-shadow: var(--shadow);
      margin-bottom: 1.5rem;
    }
    .card-centered {
      max-width: 820px;
      margin: 0 auto 1.5rem auto;
    }
    .card-title-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 1.2rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 0.6rem;
    }
    .card-title {
      font-size: 1.15rem;
      font-weight: 700;
      color: #0f172a;
    }

    /* Clean Folder Selection Box in Tab 1 */
    .folder-selection-card {
      background: #f8fafc;
      border: 1.5px dashed #cbd5e1;
      border-radius: 10px;
      padding: 1.25rem 1.5rem;
      margin-bottom: 1.25rem;
    }
    .folder-selection-header {
      display: flex;
      align-items: center;
      gap: 14px;
    }
    .folder-icon-box {
      font-size: 2.2rem;
      line-height: 1;
    }
    .folder-meta-box {
      flex: 1;
      min-width: 0;
    }
    .folder-label {
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      font-weight: 700;
      display: block;
      margin-bottom: 4px;
    }
    .folder-path-text {
      font-family: monospace;
      font-size: 1rem;
      font-weight: 600;
      color: #0369a1;
      word-break: break-all;
    }
    .folder-action-buttons {
      display: flex;
      gap: 12px;
      align-items: center;
      margin-top: 14px;
      flex-wrap: wrap;
    }

    /* Buttons */
    .btn {
      background: var(--primary);
      color: white;
      border: none;
      padding: 0.65rem 1.25rem;
      border-radius: 7px;
      font-weight: 600;
      cursor: pointer;
      font-size: 0.92rem;
      transition: all 0.15s;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .btn:hover { background: var(--primary-dark); }
    .btn-secondary { background: #64748b; }
    .btn-secondary:hover { background: #475569; }
    .btn-success { background: var(--accent-green); }
    .btn-success:hover { background: var(--accent-green-dark); }
    .btn-danger { background: var(--accent-red); }
    .btn-danger:hover { background: #dc2626; }
    .btn-sm { padding: 0.4rem 0.75rem; font-size: 0.82rem; }

    /* Scan Controls */
    .scan-sub-controls {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 1rem;
      padding-top: 1rem;
      border-top: 1px solid var(--border);
    }

    /* Progress Bar */
    .progress-bar-container {
      width: 100%;
      background: #e2e8f0;
      height: 12px;
      border-radius: 6px;
      overflow: hidden;
      margin: 1.25rem 0 0.5rem 0;
    }
    .progress-bar-fill {
      height: 100%;
      background: var(--accent-green);
      width: 0%;
      transition: width 0.3s;
    }
    .progress-label {
      font-size: 0.85rem;
      color: var(--text-muted);
      display: flex;
      justify-content: space-between;
      font-weight: 500;
    }

    /* Activity Log */
    .log-box {
      background: #0f172a;
      color: #f1f5f9;
      font-family: monospace;
      font-size: 0.82rem;
      padding: 0.9rem;
      border-radius: 7px;
      height: 150px;
      overflow-y: auto;
      white-space: pre-wrap;
      margin-top: 1rem;
      border: 1px solid #1e293b;
    }

    /* Search Tab */
    .search-bar { display: flex; gap: 0.5rem; position: relative; margin-bottom: 1rem; }
    .search-bar input[type="text"] {
      flex: 1;
      padding: 0.75rem 1rem;
      font-size: 1rem;
      border-radius: 8px;
      border: 1.5px solid var(--border);
      outline: none;
      transition: border-color 0.2s;
    }
    .search-bar input[type="text"]:focus { border-color: var(--primary); }
    .search-options {
      display: flex;
      gap: 1.25rem;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 1.25rem;
      font-size: 0.9rem;
      color: var(--text-muted);
    }
    .search-options select {
      padding: 0.4rem 0.8rem;
      border-radius: 6px;
      border: 1px solid var(--border);
    }
    .suggestions-list {
      position: absolute;
      top: 100%;
      left: 0;
      right: 0;
      background: white;
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: var(--shadow-lg);
      max-height: 220px;
      overflow-y: auto;
      z-index: 100;
      display: none;
    }
    .suggestion-item { padding: 0.55rem 0.9rem; cursor: pointer; font-size: 0.92rem; }
    .suggestion-item:hover { background: var(--primary-light); color: var(--primary-dark); }

    /* Result Cards */
    .result-card {
      background: white;
      border: 1px solid var(--border);
      border-radius: 9px;
      padding: 1.25rem;
      margin-bottom: 1rem;
      box-shadow: var(--shadow-sm);
      cursor: pointer;
      transition: all 0.15s;
    }
    .result-card:hover {
      border-color: #38bdf8;
      box-shadow: var(--shadow);
      transform: translateY(-1px);
    }
    .result-header {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 0.4rem;
    }
    .result-title {
      font-size: 1.05rem;
      font-weight: 700;
      color: var(--primary-dark);
    }
    .result-badge {
      font-size: 0.75rem;
      font-weight: 700;
      padding: 0.2rem 0.55rem;
      border-radius: 4px;
      background: var(--primary-light);
      color: var(--primary-dark);
      text-transform: uppercase;
    }
    .result-meta {
      font-size: 0.82rem;
      color: var(--text-muted);
      margin-bottom: 0.65rem;
    }
    .page-tag {
      font-weight: 700;
      color: #0369a1;
      background: #e0f2fe;
      padding: 1px 6px;
      border-radius: 4px;
    }
    .result-snippet {
      font-size: 0.92rem;
      color: #334155;
      line-height: 1.6;
    }
    mark { background: #fef08a; padding: 1px 3px; border-radius: 2px; font-weight: 600; color: #854d0e; }
    .result-footer-actions {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 0.85rem;
      padding-top: 0.75rem;
      border-top: 1px solid #f1f5f9;
    }
    .result-hint {
      font-size: 0.78rem;
      color: #94a3b8;
      font-style: italic;
    }

    /* Modal Overlays & Unified Storage Dialog */
    .modal-overlay {
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(15, 23, 42, 0.65);
      backdrop-filter: blur(2px);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 1000;
      padding: 1rem;
    }
    .modal-box {
      background: white;
      border-radius: 12px;
      width: 100%;
      max-width: 820px;
      max-height: 88vh;
      display: flex;
      flex-direction: column;
      box-shadow: var(--shadow-lg);
      overflow: hidden;
      border: 1px solid var(--border);
    }
    .modal-header {
      padding: 1rem 1.25rem;
      border-bottom: 1px solid var(--border);
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: #f8fafc;
    }
    .modal-header-title {
      font-weight: 700;
      font-size: 1.1rem;
      display: flex;
      align-items: center;
      gap: 8px;
      color: #0f172a;
    }
    .modal-close {
      background: none;
      border: none;
      font-size: 1.25rem;
      cursor: pointer;
      color: var(--text-muted);
      padding: 4px 8px;
      border-radius: 4px;
    }
    .modal-close:hover { background: #e2e8f0; color: var(--text); }
    
    /* Storage Shortcuts Bar in Unified Modal */
    .fb-shortcuts-section {
      padding: 0.65rem 1.25rem;
      background: #ffffff;
      border-bottom: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .fb-shortcuts-category {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      align-items: center;
    }
    .fb-category-label {
      font-size: 0.72rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      min-width: 90px;
    }
    .fb-shortcut-pill {
      background: #f1f5f9;
      border: 1px solid #e2e8f0;
      border-radius: 9999px;
      padding: 3px 10px;
      font-size: 0.8rem;
      font-weight: 500;
      cursor: pointer;
      color: #334155;
      transition: all 0.15s;
    }
    .fb-shortcut-pill:hover {
      background: #e0f2fe;
      color: #0369a1;
      border-color: #7dd3fc;
    }
    .pill-device {
      background: #f0fdf4;
      border-color: #bbf7d0;
      color: #166534;
      font-weight: 600;
    }
    .pill-device:hover {
      background: #dcfce7;
      border-color: #86efac;
      color: #15803d;
    }
    .pill-network {
      background: #eff6ff;
      border-color: #bfdbfe;
      color: #1d4ed8;
      font-weight: 600;
    }
    .pill-network:hover {
      background: #dbeafe;
      border-color: #93c5fd;
      color: #1e40af;
    }

    /* Direct Path Bar inside Modal */
    .fb-path-bar {
      padding: 0.65rem 1.25rem;
      background: #f8fafc;
      border-bottom: 1px solid var(--border);
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .fb-path-input {
      flex: 1;
      padding: 0.45rem 0.75rem;
      font-size: 0.88rem;
      font-family: monospace;
      border-radius: 6px;
      border: 1px solid var(--border);
      outline: none;
    }
    .fb-path-input:focus { border-color: var(--primary); }

    .fb-nav-bar {
      padding: 0.55rem 1.25rem;
      background: #ffffff;
      border-bottom: 1px solid var(--border);
      display: flex;
      gap: 10px;
      align-items: center;
    }
    .fb-breadcrumbs {
      display: flex;
      gap: 4px;
      flex-wrap: wrap;
      align-items: center;
      font-size: 0.85rem;
      overflow-x: auto;
    }
    .fb-breadcrumb-item {
      color: var(--primary);
      font-weight: 600;
      cursor: pointer;
      padding: 2px 4px;
      border-radius: 4px;
    }
    .fb-breadcrumb-item:hover {
      text-decoration: underline;
      background: #e0f2fe;
    }
    .fb-list-container {
      padding: 0.75rem 1.25rem;
      overflow-y: auto;
      flex: 1;
      max-height: 350px;
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
      gap: 6px;
      align-content: start;
    }
    .fb-dir-item {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 10px;
      border-radius: 6px;
      cursor: pointer;
      border: 1px solid transparent;
      transition: all 0.15s;
      user-select: none;
      font-size: 0.9rem;
    }
    .fb-dir-item:hover {
      background: #f1f5f9;
      border-color: #cbd5e1;
    }
    .fb-dir-item.selected {
      background: #e0f2fe;
      border-color: #38bdf8;
      color: #0369a1;
      font-weight: 600;
    }
    .fb-dir-name {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .modal-footer {
      padding: 1rem 1.25rem;
      border-top: 1px solid var(--border);
      background: #f8fafc;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 10px;
    }
    .modal-footer-info {
      flex: 1;
      min-width: 220px;
    }
    .modal-footer-label {
      font-size: 0.78rem;
      font-weight: 600;
      color: var(--text-muted);
      display: block;
    }
    .modal-footer-path {
      font-family: monospace;
      font-size: 0.88rem;
      font-weight: 600;
      word-break: break-all;
      color: var(--primary-dark);
    }

    /* ============================================================
       MINI PAGE OF ORIGINAL VERSION (Authentic Document Sheet)
       ============================================================ */
    .mini-page-modal-wrapper {
      background: #090d16;
      border-radius: 16px;
      width: 100%;
      max-width: 920px;
      height: 92vh;
      display: flex;
      flex-direction: column;
      box-shadow: 0 25px 65px -12px rgba(0, 0, 0, 0.75);
      border: 1px solid rgba(255, 255, 255, 0.1);
      overflow: hidden;
      animation: miniPageSlide 0.2s cubic-bezier(0.16, 1, 0.3, 1);
    }
    @keyframes miniPageSlide {
      from { transform: translateY(-16px) scale(0.97); opacity: 0; }
      to { transform: translateY(0) scale(1); opacity: 1; }
    }
    .mini-page-topbar {
      padding: 0.75rem 1.4rem;
      background: #0f172a;
      border-bottom: 1px solid #1e293b;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      shrink: 0;
    }
    .mini-page-topbar-left {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }
    .mini-page-type-badge {
      background: #0284c7;
      color: #ffffff;
      font-size: 0.75rem;
      font-weight: 800;
      padding: 3px 8px;
      border-radius: 6px;
      letter-spacing: 0.05em;
      text-transform: uppercase;
    }
    .mini-page-title-block { min-width: 0; }
    .mini-page-main-title {
      font-size: 0.95rem;
      font-weight: 700;
      color: #f8fafc;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 380px;
    }
    .mini-page-sub-title {
      font-size: 0.75rem;
      color: #94a3b8;
      margin-top: 1px;
    }
    .mini-page-topbar-actions {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .zoom-pill {
      display: flex;
      align-items: center;
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 20px;
      padding: 2px 6px;
      gap: 4px;
    }
    .zoom-btn {
      background: transparent;
      border: none;
      color: #94a3b8;
      cursor: pointer;
      font-size: 0.9rem;
      font-weight: 700;
      padding: 2px 6px;
      border-radius: 4px;
      transition: color 0.15s;
    }
    .zoom-btn:hover { color: #f8fafc; background: #334155; }
    .zoom-level {
      font-size: 0.75rem;
      font-family: monospace;
      color: #38bdf8;
      padding: 0 4px;
    }
    .mini-page-nav-bar {
      padding: 0.5rem 1.4rem;
      background: #0d1322;
      border-bottom: 1px solid #1e293b;
      display: flex;
      justify-content: center;
      align-items: center;
      gap: 16px;
      shrink: 0;
    }
    .stepper-badge {
      font-size: 0.85rem;
      font-weight: 600;
      color: #f1f5f9;
      background: #1e293b;
      padding: 4px 14px;
      border-radius: 12px;
      border: 1px solid #334155;
    }

    /* Workbench dark canvas where the mini sheet floats */
    .mini-page-workbench {
      flex: 1;
      overflow-y: auto;
      overflow-x: auto;
      background: #090d16;
      padding: 2.2rem 1.5rem;
      display: flex;
      justify-content: center;
      align-items: flex-start;
    }

    /* The authentic paper sheet */
    .mini-page-sheet {
      background: #ffffff;
      color: #1e293b;
      width: 100%;
      max-width: 680px;
      min-height: 840px;
      padding: 44px 50px;
      border-radius: 4px;
      border: 1px solid #cbd5e1;
      box-shadow: 0 18px 45px -8px rgba(0, 0, 0, 0.55), 0 0 0 1px rgba(255, 255, 255, 0.05);
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: transform 0.15s ease-out;
      transform-origin: top center;
    }

    /* Running Header */
    .mini-page-running-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1.5px solid #0f172a;
      padding-bottom: 8px;
      margin-bottom: 24px;
      font-size: 0.72rem;
      letter-spacing: 0.05em;
      color: #475569;
      font-weight: 600;
    }
    .running-seal {
      color: #0284c7;
      font-weight: 700;
      margin-right: 12px;
    }
    .running-archive-tag {
      background: #f1f5f9;
      border: 1px solid #cbd5e1;
      padding: 2px 7px;
      border-radius: 4px;
      font-size: 0.68rem;
      color: #0369a1;
      font-weight: 600;
      margin-right: 8px;
    }

    /* Sheet Body */
    .mini-page-sheet-body {
      flex: 1;
      font-family: Georgia, 'Times New Roman', Charter, Cambria, serif;
      font-size: 15px;
      line-height: 1.78;
      color: #1e293b;
      word-break: break-word;
    }
    .mini-page-para {
      margin-bottom: 1.15rem;
      text-align: justify;
      text-justify: inter-word;
    }
    .mini-page-heading {
      font-family: system-ui, -apple-system, sans-serif;
      font-size: 1.08rem;
      font-weight: 700;
      color: #090d16;
      margin-top: 1.4rem;
      margin-bottom: 0.5rem;
      letter-spacing: -0.01em;
      border-left: 3px solid #0284c7;
      padding-left: 8px;
    }

    /* Structured Clinical Table View */
    .mini-page-table-wrapper {
      margin: 1.15rem 0;
      overflow-x: auto;
      border: 1px solid #cbd5e1;
      border-radius: 6px;
      background: #f8fafc;
      box-shadow: 0 1px 2px rgba(0,0,0,0.03);
    }
    .mini-page-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.88rem;
      font-family: system-ui, -apple-system, sans-serif;
      line-height: 1.45;
    }
    .mini-page-table tr {
      border-bottom: 1px solid #e2e8f0;
    }
    .mini-page-table tr:last-child {
      border-bottom: none;
    }
    .mini-page-table tr:hover {
      background: #f1f5f9;
    }
    .mini-page-table td {
      padding: 7px 11px;
      vertical-align: top;
      color: #1e293b;
      border-right: 1px solid #e2e8f0;
    }
    .mini-page-table td:last-child {
      border-right: none;
    }
    .mini-page-table td:first-child {
      font-weight: 600;
      color: #0f172a;
      white-space: nowrap;
      background: rgba(241, 245, 249, 0.6);
    }

    /* High contrast clinical highlighter */
    mark.mini-page-mark,
    .mini-page-sheet-body mark {
      background-color: #fef08a;
      color: #713f12;
      font-weight: 700;
      padding: 1px 4px;
      border-radius: 3px;
      box-shadow: 0 1px 2px rgba(0,0,0,0.06);
    }

    /* Running Footer */
    .mini-page-running-footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-top: 1px solid #cbd5e1;
      padding-top: 10px;
      margin-top: 28px;
      font-size: 0.72rem;
      color: #64748b;
      font-family: monospace;
    }
    .footer-center {
      font-weight: 700;
      font-size: 0.8rem;
      color: #0f172a;
    }

    @media print {
      body * { visibility: hidden; }
      #pageNoteModal, #pageNoteModal * { visibility: visible; }
      #pageNoteModal {
        position: absolute; left: 0; top: 0; width: 100%; height: auto;
        background: white !important; display: block !important;
      }
      .mini-page-modal-wrapper {
        border: none !important; box-shadow: none !important;
        max-width: 100% !important; height: auto !important;
      }
      .mini-page-topbar, .mini-page-nav-bar { display: none !important; }
      .mini-page-workbench { background: white !important; padding: 0 !important; }
      .mini-page-sheet {
        border: none !important; box-shadow: none !important;
        max-width: 100% !important; padding: 0 !important;
      }
    }

    /* Synonyms Table */
    table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
    th, td { padding: 0.65rem 0.85rem; text-align: left; border-bottom: 1px solid var(--border); }
    th { background: #f1f5f9; font-weight: 600; color: var(--text-muted); }
  </style>
</head>
<body>

<header>
  <h1>📑 Universal Document Search & Indexer</h1>
  <div style="display:flex; align-items:center; gap:12px;">
    <a href="/pwa/" target="_blank" class="pwa-header-link" title="Open Mobile Search PWA (Offline SQLite WASM + OPFS)">📱 Mobile PWA</a>
    <div class="status-badge" id="headerStatus">● Ready</div>
  </div>
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
    <button class="tab-btn active" onclick="switchTab('tabIndexer')">1. Indexer & Scan</button>
    <button class="tab-btn" onclick="switchTab('tabSearch')">2. Full-Text Search</button>
    <button class="tab-btn" onclick="switchTab('tabSynonyms')">3. Synonym Dictionary</button>
    <button class="tab-btn" onclick="switchTab('tabExport')">4. Mobile PWA Export</button>
  </div>

  <!-- Tab 1: Indexer (Decluttered, single unified Browse Folder button) -->
  <div id="tabIndexer" class="tab-content active">
    <div class="card card-centered">
      <div class="card-title-bar">
        <div class="card-title">Document Source & Indexing</div>
        <span class="status-badge" id="indexerBadge">● Ready</span>
      </div>

      <div class="folder-selection-card">
        <div class="folder-selection-header">
          <div class="folder-icon-box" id="displayFolderIcon">📁</div>
          <div class="folder-meta-box">
            <span class="folder-label">SOURCE FOLDER TO SCAN:</span>
            <div id="displayCurrentFolder" class="folder-path-text">
              No folder selected. Click "Browse Folder..." to choose documents to index.
            </div>
          </div>
        </div>

        <div class="folder-action-buttons">
          <button class="btn btn-primary" onclick="openFolderBrowser()" id="btnBrowseFolder" title="Browse local folders, attached USB pendrives, external hard drives, or network shares" style="font-size: 1rem; padding: 0.75rem 1.6rem;">
            <span>📂</span> <strong>Browse Folder...</strong>
          </button>
          <button class="btn btn-success" id="btnStartScan" onclick="startScan()" style="margin-left: auto; font-size: 1rem; padding: 0.75rem 1.8rem;">
            <span>🚀</span> <strong>Start Indexing</strong>
          </button>
        </div>
      </div>

      <!-- Controls row (active during scanning) -->
      <div class="scan-sub-controls" id="scanControls" style="display: none;">
        <button class="btn btn-sm btn-secondary" onclick="controlScan('pause')">⏸️ Pause</button>
        <button class="btn btn-sm btn-secondary" onclick="controlScan('resume')">▶️ Resume</button>
        <button class="btn btn-sm btn-danger" onclick="controlScan('cancel')">⏹️ Cancel</button>
        <button class="btn btn-sm btn-secondary" onclick="retryFailed()">🔄 Retry Failed</button>
      </div>

      <!-- Progress Section -->
      <div class="progress-bar-container">
        <div class="progress-bar-fill" id="progressFill"></div>
      </div>
      <div class="progress-label">
        <span id="progressFile">Ready to scan</span>
        <span id="progressPct">0%</span>
      </div>

      <div class="log-box" id="activityLogs">Indexer ready. Click 'Browse Folder...' to select a local directory, USB pendrive, external hard disk, or network share, then click 'Start Indexing'.</div>
    </div>
  </div>

  <!-- Tab 2: Search -->
  <div id="tabSearch" class="tab-content">
    <div class="card">
      <div class="card-title">Instant Full-Text Document Search</div>
      <div class="search-bar">
        <input type="text" id="searchInput" placeholder="Search documents (e.g. 'annual report', 'specifications', 'contract', 'summary*')..." oninput="onSearchInput()" onkeydown="if(event.key==='Enter')performSearch();">
        <button class="btn" onclick="performSearch()">Search</button>
        <div class="suggestions-list" id="suggestionsList"></div>
      </div>
      <div class="search-options">
        <label style="display:flex; align-items:center; gap:0.4rem; cursor:pointer;">
          <input type="checkbox" id="chkSynonyms" checked>
          <strong>Expand Synonyms / Acronyms</strong> (e.g. AI &harr; Artificial Intelligence)
        </label>
        <div>
          <label>File Format: </label>
          <select id="selFormat" onchange="performSearch()">
            <option value="all">All Formats (.pdf, .docx, .doc, .txt)</option>
            <option value="pdf">PDF only</option>
            <option value="docx">DOCX only</option>
            <option value="doc">Legacy DOC only</option>
            <option value="txt">Text only</option>
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
      <div class="card-title">Custom Synonym & Acronym Dictionary</div>
      <div style="display:flex; gap:0.5rem; margin-bottom:1.5rem; flex-wrap:wrap;">
        <input type="text" id="newSynTerm" placeholder="Term / Acronym (e.g. AI, Q1, SOW)" style="flex:1; min-width:200px; padding:0.6rem; border:1px solid var(--border); border-radius:6px;">
        <input type="text" id="newSynExpanded" placeholder="Full Expansion / Synonyms (e.g. Statement of Work)" style="flex:2; min-width:280px; padding:0.6rem; border:1px solid var(--border); border-radius:6px;">
        <button class="btn" onclick="addSynonym()">➕ Add Synonym</button>
      </div>

      <table>
        <thead>
          <tr>
            <th style="width:25%;">Term / Acronym</th>
            <th>Expansion / Synonyms</th>
          </tr>
        </thead>
        <tbody id="synonymsTableBody"></tbody>
      </table>
    </div>
  </div>

  <!-- Tab 4: Export -->
  <div id="tabExport" class="tab-content">
    <div class="card">
      <div class="card-title">Mobile PWA & Offline Database Exporter</div>
      <p style="color:var(--text-muted); font-size:0.9rem; margin-bottom:1.2rem;">
        Generate lightweight, portable SQLite search databases with streaming Zstandard compression for offline clinical search.
      </p>

      <div style="background:#f8fafc; border:1px solid var(--border); border-radius:8px; padding:1.2rem; margin-bottom:1.5rem;" id="exportPreviewBox">
        <div style="font-weight:600; margin-bottom:0.5rem;">Estimated Sizing Preview:</div>
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:1rem; font-size:0.9rem;">
          <div>Full DB Size: <strong id="expActualSize">--</strong></div>
          <div>Compact Search DB: <strong id="expCompactSize">--</strong></div>
          <div>Compressed Zstandard: <strong id="expZstdSize" style="color:var(--accent-green-dark);">-- (~95% reduction)</strong></div>
        </div>
      </div>

      <div style="display:flex; gap:1.5rem; flex-wrap:wrap; margin-bottom:1.5rem;">
        <label><input type="radio" name="expType" value="compact" checked> <strong>Search-Only Compact DB</strong></label>
        <label><input type="radio" name="expType" value="full"> <strong>Full Database</strong></label>
        <label><input type="radio" name="expType" value="incremental"> <strong>Incremental Delta</strong></label>
      </div>

      <div style="margin-bottom:1.5rem;">
        <label style="display:flex; align-items:center; gap:0.5rem; cursor:pointer;">
          <input type="checkbox" id="chkZstdCompress" checked>
          Enable Zstandard Ultra-Compression (level 10)
        </label>
      </div>

      <button class="btn btn-success" id="btnExport" onclick="generateExport()">
        🚀 Generate & Download Export
      </button>

      <div id="exportResultBox" style="margin-top:1.5rem; display:none;"></div>
    </div>
  </div>
</div>

<!-- Unified Storage & Folder Browser Modal (Local, Attached USB, External HDD, and Network Shares) -->
<div id="folderBrowserModal" class="modal-overlay" style="display: none;" onclick="if(event.target===this)closeFolderBrowser();">
  <div class="modal-box">
    <div class="modal-header">
      <div class="modal-header-title">
        <span>📂</span> Browse Storage & Select Folder
      </div>
      <button class="modal-close" onclick="closeFolderBrowser()" title="Close (Esc)">✕</button>
    </div>

    <!-- Storage Shortcuts Section (Local, USB Pendrives, External HDDs, Network Shares) -->
    <div class="fb-shortcuts-section">
      <!-- Attached Removable Devices (Pendrives / External Hard Drives) -->
      <div class="fb-shortcuts-category" id="fbDevicesRow" style="display:none;">
        <span class="fb-category-label">🔌 Attached:</span>
        <div id="fbDevicesPills" style="display:flex; gap:6px; flex-wrap:wrap;"></div>
      </div>

      <!-- Network Shares -->
      <div class="fb-shortcuts-category" id="fbNetworkRow" style="display:none;">
        <span class="fb-category-label">🌐 Network:</span>
        <div id="fbNetworkPills" style="display:flex; gap:6px; flex-wrap:wrap;"></div>
      </div>

      <!-- Local Shortcuts -->
      <div class="fb-shortcuts-category">
        <span class="fb-category-label">📁 Local:</span>
        <div id="fbLocalPills" style="display:flex; gap:6px; flex-wrap:wrap;"></div>
      </div>
    </div>

    <!-- Direct Path Entry / UNC Network Share Input -->
    <div class="fb-path-bar">
      <span style="font-size:0.8rem; font-weight:700; color:var(--text-muted);">PATH:</span>
      <input type="text" id="fbDirectInput" class="fb-path-input" placeholder="Enter path or \\server\share or /media/user/USB..." onkeydown="if(event.key==='Enter')fbGoDirect();">
      <button class="btn btn-sm btn-primary" onclick="fbGoDirect()">Go / Connect</button>
    </div>

    <!-- Navigation & Breadcrumbs -->
    <div class="fb-nav-bar">
      <button class="btn btn-sm btn-secondary" id="fbUpBtn" onclick="fbGoUp()">⬆️ Up</button>
      <div class="fb-breadcrumbs" id="fbBreadcrumbs"></div>
    </div>

    <!-- Folder Grid -->
    <div class="fb-list-container" id="fbDirList">
      <div style="text-align: center; color: var(--text-muted); padding: 2.5rem;">Loading directories...</div>
    </div>

    <!-- Modal Footer -->
    <div class="modal-footer">
      <div class="modal-footer-info">
        <span class="modal-footer-label">Selected Folder:</span>
        <span id="fbSelectedPath" class="modal-footer-path"></span>
      </div>
      <div style="display: flex; gap: 8px;">
        <button class="btn btn-secondary" onclick="closeFolderBrowser()">Cancel</button>
        <button class="btn btn-primary" onclick="confirmFolderSelection()">
          ✅ Select This Folder
        </button>
      </div>
    </div>
  </div>
</div>

<!-- Page Note Modal (Authentic Mini Page of Original Version) -->
<div id="pageNoteModal" class="modal-overlay" style="display: none;" onclick="if(event.target===this)closePageNote();">
  <div class="mini-page-modal-wrapper">
    <!-- Topbar / Controls -->
    <div class="mini-page-topbar">
      <div class="mini-page-topbar-left">
        <span class="mini-page-type-badge" id="miniPageFormatBadge">PDF</span>
        <div class="mini-page-title-block">
          <div class="mini-page-main-title" id="miniPageDocTitle">Document Title</div>
          <div class="mini-page-sub-title" id="miniPageDocMeta">Page 1 of 1</div>
        </div>
      </div>

      <!-- Action Tools -->
      <div class="mini-page-topbar-actions">
        <div class="zoom-pill">
          <button class="zoom-btn" onclick="adjustMiniPageZoom(-0.1)" title="Zoom Out (–)">−</button>
          <span class="zoom-level" id="miniPageZoomText">100%</span>
          <button class="zoom-btn" onclick="adjustMiniPageZoom(0.1)" title="Zoom In (+)">+</button>
          <button class="zoom-btn" onclick="resetMiniPageZoom()" title="Reset Zoom (100%)">⟲</button>
        </div>
        <button class="btn btn-sm btn-secondary" onclick="printMiniPage()" title="Print / Export Page Sheet">🖨️ Print</button>
        <button class="btn btn-sm btn-secondary" onclick="copyNoteContent()" title="Copy clean page text">📋 Copy Text</button>
        <button class="modal-close" onclick="closePageNote()" title="Close (Esc)">✕</button>
      </div>
    </div>

    <!-- Navigation Stepper -->
    <div class="mini-page-nav-bar">
      <button class="btn btn-sm btn-secondary" id="btnPrevPage" onclick="navigateNotePage(-1)" title="Previous Page (Left Arrow)">◀ Previous Page</button>
      <div class="stepper-badge" id="miniPageNumberBadge">Page 1 / 1</div>
      <button class="btn btn-sm btn-secondary" id="btnNextPage" onclick="navigateNotePage(1)" title="Next Page (Right Arrow)">Next Page ▶</button>
    </div>

    <!-- Dark Workbench with Centered Authentic Paper Page Sheet -->
    <div class="mini-page-workbench" id="miniPageWorkbench">
      <div class="mini-page-sheet" id="miniPageSheet">
        <!-- Running Header -->
        <div class="mini-page-running-header">
          <div class="running-left">
            <span class="running-seal">📄 DOCUMENT ARCHIVE</span>
            <span class="running-doc-name" id="runningDocName">DOCUMENT</span>
          </div>
          <div class="running-right">
            <span class="running-archive-tag" id="runningArchiveTag" style="display: none;">📦 ARCHIVE</span>
            <span class="running-pg-label" id="runningHeaderPage">PAGE 1</span>
          </div>
        </div>

        <!-- Sheet Body -->
        <div class="mini-page-sheet-body" id="miniPageSheetBody">
          <div style="text-align: center; color: #94a3b8; padding: 4rem;">Loading authentic page sheet...</div>
        </div>

        <!-- Running Footer -->
        <div class="mini-page-running-footer">
          <div class="footer-left" id="runningFooterPath">Source Path</div>
          <div class="footer-center" id="runningFooterPageCounter">— Page 1 of 1 —</div>
          <div class="footer-right">DOCUMENT PREVIEW</div>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
  let debounceTimer = null;
  let currentSelectedFolderPath = '';
  let browserCurrentPath = '';
  let browserParentPath = null;

  // Page Note State
  let currentNoteDocId = 0;
  let currentNotePage = 1;
  let currentNoteTotalPages = 1;
  let currentSearchQuery = '';

  function switchTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    event.currentTarget.classList.add('active');
    document.getElementById(tabId).classList.add('active');
    if (tabId === 'tabSynonyms') loadSynonyms();
    if (tabId === 'tabExport') loadExportPreview();
  }

  // --- Unified Folder & Storage Browser ---
  function openFolderBrowser() {
    const modal = document.getElementById('folderBrowserModal');
    if (modal) modal.style.display = 'flex';
    loadDirectory(currentSelectedFolderPath || '');
  }

  function closeFolderBrowser() {
    const modal = document.getElementById('folderBrowserModal');
    if (modal) modal.style.display = 'none';
  }

  async function loadDirectory(path) {
    const listEl = document.getElementById('fbDirList');
    if (!listEl) return;
    listEl.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 2.5rem;">Loading storage...</div>';

    try {
      const url = '/api/fs/browse' + (path ? '?path=' + encodeURIComponent(path) : '');
      const res = await fetch(url);
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();

      browserCurrentPath = data.current_path;
      browserParentPath = data.parent_path;

      const pathDisplay = document.getElementById('fbSelectedPath');
      if (pathDisplay) pathDisplay.textContent = browserCurrentPath;

      const inputDisplay = document.getElementById('fbDirectInput');
      if (inputDisplay) inputDisplay.value = browserCurrentPath;

      const upBtn = document.getElementById('fbUpBtn');
      if (upBtn) {
        const canGoUp = Boolean(browserParentPath && browserParentPath !== browserCurrentPath);
        upBtn.disabled = !canGoUp;
        upBtn.style.opacity = canGoUp ? '1' : '0.4';
      }

      // Render Attached Removable Devices (USB Pendrives, External HDDs)
      const devRow = document.getElementById('fbDevicesRow');
      const devPills = document.getElementById('fbDevicesPills');
      if (data.attached_devices && data.attached_devices.length > 0) {
        devRow.style.display = 'flex';
        devPills.innerHTML = data.attached_devices.map(d => {
          const safeP = encodeURIComponent(d.path);
          return `<span class="fb-shortcut-pill pill-device" onclick="loadDirectory(decodeURIComponent('${safeP}'))">${escapeHtml(d.name)}</span>`;
        }).join('');
      } else {
        devRow.style.display = 'none';
      }

      // Render Network Shares
      const netRow = document.getElementById('fbNetworkRow');
      const netPills = document.getElementById('fbNetworkPills');
      if (data.network_mounts && data.network_mounts.length > 0) {
        netRow.style.display = 'flex';
        netPills.innerHTML = data.network_mounts.map(m => {
          const safeP = encodeURIComponent(m.path);
          return `<span class="fb-shortcut-pill pill-network" onclick="loadDirectory(decodeURIComponent('${safeP}'))">${escapeHtml(m.name)}</span>`;
        }).join('');
      } else {
        netRow.style.display = 'none';
      }

      // Render Local Shortcuts
      const localPills = document.getElementById('fbLocalPills');
      if (localPills && data.shortcuts) {
        localPills.innerHTML = data.shortcuts.map(s => {
          const safeP = encodeURIComponent(s.path);
          return `<span class="fb-shortcut-pill" onclick="loadDirectory(decodeURIComponent('${safeP}'))">${escapeHtml(s.name)}</span>`;
        }).join('');
      }

      // Render Breadcrumbs
      const bcEl = document.getElementById('fbBreadcrumbs');
      if (bcEl && data.breadcrumbs) {
        bcEl.innerHTML = data.breadcrumbs.map((b, i) => {
          const safeP = encodeURIComponent(b.path);
          return `${i > 0 ? '<span style="color:#94a3b8;">/</span>' : ''}<span class="fb-breadcrumb-item" onclick="loadDirectory(decodeURIComponent('${safeP}'))">${escapeHtml(b.name)}</span>`;
        }).join('');
      }

      // Render Subdirectories
      if (!data.subdirectories || data.subdirectories.length === 0) {
        listEl.innerHTML = '<div style="color: #94a3b8; padding: 2.5rem; text-align: center; grid-column: 1 / -1;">(No subfolders found in this folder)</div>';
      } else {
        listEl.innerHTML = data.subdirectories.map(d => {
          const safeP = encodeURIComponent(d.path);
          return `
            <div class="fb-dir-item" ondblclick="loadDirectory(decodeURIComponent('${safeP}'))" onclick="selectFbItem(this, decodeURIComponent('${safeP}'))">
              <span style="font-size: 1.25rem;">📁</span>
              <span class="fb-dir-name">${escapeHtml(d.name)}</span>
            </div>
          `;
        }).join('');
      }
    } catch (e) {
      listEl.innerHTML = `<div style="color: var(--accent-red); padding: 2rem; text-align: center; grid-column: 1 / -1;">Failed to load directory: ${escapeHtml(e.message)}</div>`;
    }
  }

  function selectFbItem(el, path) {
    document.querySelectorAll('.fb-dir-item').forEach(item => item.classList.remove('selected'));
    el.classList.add('selected');
    browserCurrentPath = path;
    const pathDisplay = document.getElementById('fbSelectedPath');
    if (pathDisplay) pathDisplay.textContent = path;
    const inputDisplay = document.getElementById('fbDirectInput');
    if (inputDisplay) inputDisplay.value = path;
  }

  function fbGoUp() {
    if (browserParentPath) {
      loadDirectory(browserParentPath);
    }
  }

  async function fbGoDirect() {
    const input = document.getElementById('fbDirectInput');
    const val = input.value.trim();
    if (!val) return;

    // Check if network UNC or non-local path
    if (val.startsWith('\\\\') || val.startsWith('//') || val.startsWith('smb://')) {
      input.disabled = true;
      try {
        const res = await fetch('/api/fs/check_path', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: val })
        });
        const d = await res.json();
        if (d.valid) {
          loadDirectory(d.resolved_path);
        } else {
          alert('Network Share Error: ' + (d.error || 'Could not reach share.'));
        }
      } catch (e) {
        loadDirectory(val);
      } finally {
        input.disabled = false;
      }
    } else {
      loadDirectory(val);
    }
  }

  function confirmFolderSelection() {
    if (browserCurrentPath) {
      currentSelectedFolderPath = browserCurrentPath;
      updateSelectedFolderDisplay();
    }
    closeFolderBrowser();
  }

  function updateSelectedFolderDisplay() {
    const el = document.getElementById('displayCurrentFolder');
    const iconEl = document.getElementById('displayFolderIcon');
    if (!el) return;

    const p = currentSelectedFolderPath || '';
    const pLower = p.toLowerCase();

    if (!p) {
      if (iconEl) iconEl.textContent = '📁';
      el.textContent = 'No folder selected. Click "Browse Folder..." to choose documents to index.';
    } else if (pLower.endsWith('.zip') || pLower.endsWith('.tar.gz') || pLower.endsWith('.tgz') || pLower.endsWith('.tar')) {
      if (iconEl) iconEl.textContent = '📦';
      el.textContent = 'Compressed Archive: ' + p;
    } else if (pLower.startsWith('\\') || pLower.startsWith('smb://') || pLower.includes('gvfs')) {
      if (iconEl) iconEl.textContent = '🌐';
      el.textContent = 'Network Share: ' + p;
    } else if (pLower.includes('/media/') || pLower.includes('/run/media/') || pLower.includes('usb')) {
      if (iconEl) iconEl.textContent = '🔌';
      el.textContent = 'Attached Device: ' + p;
    } else {
      if (iconEl) iconEl.textContent = '📁';
      el.textContent = p;
    }
  }

  // --- Indexer Scan ---
  async function startScan() {
    const folder = currentSelectedFolderPath;
    if (!folder) {
      alert('Please click "Browse Folder..." to choose a folder or compressed archive first.');
      return;
    }
    const folders = [folder];

    document.getElementById('activityLogs').textContent = 'Starting indexing scan for: ' + folder;
    document.getElementById('scanControls').style.display = 'flex';
    document.getElementById('indexerBadge').textContent = '● Indexing...';
    document.getElementById('indexerBadge').style.color = '#f59e0b';
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

  async function checkProgress() {
    try {
      const res = await fetch('/api/scan/progress');
      const p = await res.json();

      const pct = p.total > 0 ? Math.round((p.current / p.total) * 100) : 0;
      document.getElementById('progressFill').style.width = pct + '%';
      document.getElementById('progressPct').textContent = pct + '%';
      document.getElementById('progressFile').textContent = p.filename ? `${p.filename} (${p.current}/${p.total})` : p.message;

      if (p.logs && p.logs.length > 0) {
        const box = document.getElementById('activityLogs');
        box.textContent = p.logs.join('\n');
        box.scrollTop = box.scrollHeight;
      }
      if (p.is_indexing) {
        document.getElementById('indexerBadge').textContent = '● Indexing...';
        document.getElementById('indexerBadge').style.color = '#f59e0b';
        setTimeout(checkProgress, 800);
      } else {
        document.getElementById('indexerBadge').textContent = '● Ready';
        document.getElementById('indexerBadge').style.color = '#38bdf8';
        loadStats();
      }
    } catch (e) {
      console.error(e);
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

  // --- Search & Page Notes ---
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
        list.innerHTML = d.suggestions.map(s => `
          <div class="suggestion-item" onclick="applySuggestion('${escapeHtml(s)}')">${escapeHtml(s)}</div>
        `).join('');
        list.style.display = 'block';
      } else {
        list.style.display = 'none';
      }
    }, 200);
  }

  function applySuggestion(text) {
    document.getElementById('searchInput').value = text;
    document.getElementById('suggestionsList').style.display = 'none';
    performSearch();
  }

  async function performSearch() {
    document.getElementById('suggestionsList').style.display = 'none';
    const q = document.getElementById('searchInput').value.trim();
    if (!q) return;

    const expandSyn = document.getElementById('chkSynonyms').checked;
    const fmt = document.getElementById('selFormat').value;

    const url = `/api/search?q=${encodeURIComponent(q)}&synonyms=${expandSyn}&format=${fmt}`;
    const res = await fetch(url);
    const d = await res.json();

    const metricsEl = document.getElementById('searchMetrics');
    metricsEl.textContent = `Found ${d.total_count} results in ${d.execution_time_ms.toFixed(1)} ms. Parsed FTS5: ${d.parsed_query}`;

    const listEl = document.getElementById('searchResultsList');
    if (d.results.length === 0) {
      listEl.innerHTML = '<div style="padding:2.5rem; text-align:center; color:var(--text-muted);">No documents matched your query.</div>';
      return;
    }

    listEl.innerHTML = d.results.map(r => `
      <div class="result-card" onclick="openPageNote(${r.document_id}, ${r.page_number}, decodeURIComponent('${encodeURIComponent(d.query)}'))">
        <div class="result-header">
          <span class="result-title">${escapeHtml(r.title || r.filename)}</span>
          <span class="result-badge">${r.file_type}</span>
        </div>
        <div class="result-meta">
          📁 ${escapeHtml(r.filename)} &bull; <span class="page-tag">Page ${r.page_number}</span> &bull; Score: ${r.rank_score.toFixed(2)}
        </div>
        <div class="result-snippet">${r.snippet_html}</div>
        <div class="result-footer-actions">
          <button class="btn btn-sm btn-primary" onclick="event.stopPropagation(); openPageNote(${r.document_id}, ${r.page_number}, decodeURIComponent('${encodeURIComponent(d.query)}'));">
            📝 Open Page Note (Page ${r.page_number})
          </button>
          <span class="result-hint">Click card to open page note</span>
        </div>
      </div>
    `).join('');
  }

  // --- Authentic Mini Page Note View Implementation ---
  let miniPageZoomLevel = 1.0;

  function adjustMiniPageZoom(delta) {
    miniPageZoomLevel = Math.min(1.8, Math.max(0.6, Math.round((miniPageZoomLevel + delta) * 10) / 10));
    applyMiniPageZoom();
  }

  function resetMiniPageZoom() {
    miniPageZoomLevel = 1.0;
    applyMiniPageZoom();
  }

  function applyMiniPageZoom() {
    const sheet = document.getElementById('miniPageSheet');
    const zoomText = document.getElementById('miniPageZoomText');
    if (sheet) sheet.style.transform = `scale(${miniPageZoomLevel})`;
    if (zoomText) zoomText.textContent = `${Math.round(miniPageZoomLevel * 100)}%`;
  }

  function printMiniPage() {
    window.print();
  }

  async function openPageNote(docId, pageNumber, query) {
    currentNoteDocId = docId;
    currentNotePage = pageNumber || 1;
    currentSearchQuery = query || document.getElementById('searchInput')?.value?.trim() || '';

    const modal = document.getElementById('pageNoteModal');
    if (modal) modal.style.display = 'flex';

    await loadNotePage(currentNoteDocId, currentNotePage);
  }

  function closePageNote() {
    const modal = document.getElementById('pageNoteModal');
    if (modal) modal.style.display = 'none';
  }

  function highlightMatches(text, query) {
    if (!text) return '';
    let safe = escapeHtml(text);
    if (!query) return safe;
    const terms = query
      .replace(/[+\-*()"]/g, ' ')
      .split(/\s+/)
      .filter(t => t.length > 2);

    for (const term of terms) {
      try {
        const escapedTerm = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const regex = new RegExp(`(${escapedTerm})`, 'gi');
        safe = safe.replace(regex, '<mark class="mini-page-mark">$1</mark>');
      } catch (e) {}
    }
    return safe;
  }

  function renderSheetContent(rawContent, query) {
    if (!rawContent || !rawContent.trim()) {
      return '<div style="color: #94a3b8; text-align: center; padding: 4rem; font-style: italic;">(This page contains no extractable text or is a blank / graphic-only page)</div>';
    }

    const blocks = rawContent.split(/\n\s*\n/);
    let html = '';

    for (const block of blocks) {
      const clean = block.trim();
      if (!clean) continue;

      const lines = clean.split('\n').map(l => l.trim()).filter(Boolean);
      const isTable = clean.startsWith('[Table]') || lines.some(l => l.includes('|'));

      if (isTable) {
        // Strip [Table] label and render as structured table
        const rowLines = lines.filter(l => l !== '[Table]');
        html += '<div class="mini-page-table-wrapper"><table class="mini-page-table"><tbody>';
        for (const rowLine of rowLines) {
          const cells = rowLine.split('|').map(c => c.trim()).filter(Boolean);
          // Deduplicate consecutive identical cells
          const deduped = [];
          for (const c of cells) {
            const norm = c.replace(/\s+/g, ' ');
            if (deduped.length === 0 || deduped[deduped.length - 1].replace(/\s+/g, ' ') !== norm) {
              deduped.push(c);
            }
          }
          if (deduped.length === 0) continue;
          html += '<tr>';
          for (let i = 0; i < deduped.length; i++) {
            const isLabel = (i === 0 && (deduped[i].endsWith(':') || deduped.length > 1));
            const tdStyle = isLabel ? 'font-weight: 600; color: #0f172a; white-space: nowrap;' : '';
            html += `<td style="${tdStyle}">${highlightMatches(deduped[i], query)}</td>`;
          }
          html += '</tr>';
        }
        html += '</tbody></table></div>';
      } else {
        const isHeading = clean.length < 90 && (
          /^(?:[0-9]+[.)]|table|figure|section|abstract|introduction|methods|results|discussion|conclusion|references|guideline|background)/i.test(clean) ||
          (clean === clean.toUpperCase() && clean.length > 4)
        );

        if (isHeading) {
          html += `<div class="mini-page-heading">${highlightMatches(clean, query)}</div>`;
        } else {
          html += `<div class="mini-page-para">${highlightMatches(clean, query)}</div>`;
        }
      }
    }

    return html;
  }

  async function loadNotePage(docId, pageNum) {
    const container = document.getElementById('miniPageSheetBody');
    if (container) {
      container.innerHTML = '<div style="text-align: center; color: #94a3b8; padding: 4rem;">Loading authentic page sheet...</div>';
    }

    try {
      const res = await fetch(`/api/document/page?doc_id=${docId}&page=${pageNum}`);
      if (!res.ok) throw new Error('Failed to load page content.');
      const data = await res.json();

      currentNotePage = data.page_number;
      currentNoteTotalPages = data.total_pages;

      // Update Topbar and Running Headers
      const formatBadge = document.getElementById('miniPageFormatBadge');
      if (formatBadge) formatBadge.textContent = data.extension || 'DOC';

      const docTitle = document.getElementById('miniPageDocTitle');
      if (docTitle) docTitle.textContent = data.doc_title || data.filename;

      const docMeta = document.getElementById('miniPageDocMeta');
      if (docMeta) docMeta.textContent = `${data.extension} Document • Page ${data.page_number} of ${data.total_pages}`;

      const runningDoc = document.getElementById('runningDocName');
      if (runningDoc) runningDoc.textContent = (data.doc_title || data.filename).toUpperCase();

      const runningArchive = document.getElementById('runningArchiveTag');
      if (runningArchive) {
        if (data.is_archive) {
          runningArchive.style.display = 'inline-block';
          runningArchive.textContent = `📦 ${data.archive_name || 'ARCHIVE'}`;
        } else {
          runningArchive.style.display = 'none';
        }
      }

      const runningHeaderPage = document.getElementById('runningHeaderPage');
      if (runningHeaderPage) runningHeaderPage.textContent = `PAGE ${data.page_number}`;

      const stepperBadge = document.getElementById('miniPageNumberBadge');
      if (stepperBadge) stepperBadge.textContent = `Page ${data.page_number} / ${data.total_pages}`;

      const footerPath = document.getElementById('runningFooterPath');
      if (footerPath) footerPath.textContent = data.source_path || data.filename;

      const footerCounter = document.getElementById('runningFooterPageCounter');
      if (footerCounter) footerCounter.textContent = `— Page ${data.page_number} of ${data.total_pages} —`;

      const btnPrev = document.getElementById('btnPrevPage');
      const btnNext = document.getElementById('btnNextPage');
      if (btnPrev) {
        btnPrev.disabled = (currentNotePage <= 1);
        btnPrev.style.opacity = (currentNotePage <= 1) ? '0.4' : '1';
      }
      if (btnNext) {
        btnNext.disabled = (currentNotePage >= currentNoteTotalPages);
        btnNext.style.opacity = (currentNotePage >= currentNoteTotalPages) ? '0.4' : '1';
      }

      if (container) {
        container.innerHTML = renderSheetContent(data.content, currentSearchQuery);
      }
    } catch (e) {
      if (container) {
        container.innerHTML = `<div style="color: var(--accent-red); padding: 2.5rem; text-align: center;">Error loading note: ${escapeHtml(e.message)}</div>`;
      }
    }
  }

  function navigateNotePage(delta) {
    const target = currentNotePage + delta;
    if (target >= 1 && target <= currentNoteTotalPages) {
      loadNotePage(currentNoteDocId, target);
    }
  }

  function copyNoteContent() {
    const container = document.getElementById('miniPageSheetBody');
    if (!container) return;
    const text = container.innerText || container.textContent;
    navigator.clipboard.writeText(text).then(() => {
      alert('Page text copied to clipboard!');
    }).catch(() => {
      alert('Could not copy automatically. You can manually select and copy the text.');
    });
  }

  // Keyboard navigation for Mini Page Modal (Arrow keys to flip pages, Esc to close)
  document.addEventListener('keydown', (e) => {
    const modal = document.getElementById('pageNoteModal');
    if (!modal || modal.style.display === 'none') return;
    if (e.key === 'Escape') closePageNote();
    else if (e.key === 'ArrowLeft') navigateNotePage(-1);
    else if (e.key === 'ArrowRight') navigateNotePage(1);
  });

  // --- Synonyms Tab ---
  async function loadSynonyms() {
    const res = await fetch('/api/synonyms');
    const d = await res.json();
    const tbody = document.getElementById('synonymsTableBody');
    tbody.innerHTML = d.synonyms.map(s => `
      <tr>
        <td><strong>${escapeHtml(s.term)}</strong></td>
        <td>${escapeHtml(s.expansion)}</td>
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

  // --- Export Tab ---
  async function loadExportPreview() {
    const res = await fetch('/api/export/preview');
    const d = await res.json();
    document.getElementById('expActualSize').textContent = d.actual_db_size_fmt;
    document.getElementById('expCompactSize').textContent = d.estimated_search_db_size_fmt;
    document.getElementById('expZstdSize').textContent = d.estimated_zstd_size_fmt;
  }

  async function generateExport() {
    const btn = document.getElementById('btnExport');
    btn.disabled = true;
    btn.textContent = '⏳ Compressing & Exporting...';
    const type = document.querySelector('input[name="expType"]:checked').value;
    const compress = document.getElementById('chkZstdCompress').checked;

    try {
      const res = await fetch('/api/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type, compress })
      });
      const d = await res.json();
      const box = document.getElementById('exportResultBox');
      box.style.display = 'block';
      if (d.error) {
        box.innerHTML = `<div style="color:var(--accent-red);">Export failed: ${escapeHtml(d.error)}</div>`;
      } else {
        box.innerHTML = `
          <div style="background:#f0fdf4; border:1px solid #86efac; border-radius:8px; padding:1.2rem;">
            <div style="color:#166534; font-weight:700; margin-bottom:0.5rem;">✅ Export Package Generated Successfully!</div>
            <div style="font-size:0.9rem; color:#14532d;">
              File: <strong>${escapeHtml(d.filename)}</strong> (${d.file_size_fmt})<br>
              Compression: <strong>${escapeHtml(d.compression_ratio)}</strong><br>
              SHA-256: <code style="font-size:0.8rem;">${escapeHtml(d.sha256)}</code>
            </div>
            <div style="margin-top:1rem;">
              <a href="${escapeHtml(d.download_url)}" download class="btn btn-success" style="text-decoration:none; display:inline-flex;">
                📥 Download ${escapeHtml(d.filename)}
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

  // --- Stats Dashboard ---
  async function loadStats() {
    try {
      const res = await fetch('/api/stats');
      const d = await res.json();
      document.getElementById('mTotalDocs').textContent = d.total_documents.toLocaleString();
      document.getElementById('mOriginalSize').textContent = d.total_original_file_size_fmt;
      document.getElementById('mDbSize').textContent = d.database_size_fmt;
      document.getElementById('mScannedPdfs').textContent = d.number_of_scanned_pdfs.toLocaleString();
      document.getElementById('mWordDocs').textContent = `${d.number_of_word_documents} Word Docs`;
      document.getElementById('mPdfPages').textContent = `${d.number_of_pdf_pages} PDF Pages`;
      document.getElementById('mTextSize').textContent = `${d.extracted_text_size_fmt} Text`;
      document.getElementById('mLastIndexed').textContent = d.last_indexing_date;
    } catch (e) {
      console.error(e);
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  }

  // Escape key handler to close modals
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      closePageNote();
      closeFolderBrowser();
    }
  });

  // Initial load
  updateSelectedFolderDisplay();
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
    print("      UNIVERSAL DOCUMENT SEARCH — WEB DASHBOARD & API")
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
